import json
import time
import ipfshttpclient
from ravenrpc import Ravencoin
import dns.zone
import dns.name
import dns.rdataset
import dns.rdata
import dns.rdatatype
import dns.update
import dns.query
import logging
import os
import config

class EvermoreWatcher:
    def __init__(self, rpc_user, rpc_password, rpc_host, rpc_port, bind_server, zone_name):
        # Initialize RavenRPC connection
        self.rpc = Ravencoin(
            rpc_user,
            rpc_password,
            host=rpc_host,
            port=rpc_port,
            #protocol='http'
        )
        
        try:
            # Test connection
            last_block = self.rpc.getblockcount()
            print(f"Successfully connected to RPC. Current block: {last_block}")
        except Exception as e:
            print(f"Failed to connect to RPC: {str(e)}")
            raise
        
        # Connect to local IPFS daemon
        try:
            ipfs = ipfshttpclient.connect()
        except:
            ipfs = ipfshttpclient.connect("/dns/squawker.app/tcp/8080/http")
        self.bind_server = bind_server
        self.zone_name = zone_name
        self.logger = logging.getLogger('EvermoreWatcher')
        
        # Squawker protocol configuration
        self.dns_prefix = "dns:"
        self.min_confirmations = 1
        self.dns_asset = "SATORI"
        self.dns_amount = 1.0

    def watch_blocks(self):
        """Watch for new blocks on the Evermore blockchain"""
        last_block = self.rpc.getblockcount()
        
        while True:
            try:
                current_block = self.rpc.getblockcount()
                if current_block > last_block:
                    self.process_block(current_block)
                    last_block = current_block
                time.sleep(10)  # Wait 10 seconds before checking for new blocks
            except Exception as e:
                print(type(e), str(e))
                self.logger.error(f"Error processing block: {str(e)}")
                
    def process_block(self, block_number):
        """Process a single block for DNS-related transactions"""
        block_hash = self.rpc.getblockhash(block_number)
        block = self.rpc.getblock(block_hash, 2)  # 2 for verbose transaction data
        
        for tx in block['tx']:
            if self.is_dns_transaction(tx):
                try:
                    # Get the sender's address for the subdomain
                    sender_address = self.get_sender_address(tx)
                    ipfs_hash = self.extract_ipfs_hash(tx)
                    dns_record = self.fetch_dns_record(ipfs_hash)
                    self.update_bind_zone(dns_record, sender_address)
                except Exception as e:
                    self.logger.error(f"Error processing transaction: {str(e)}")
                    
    def is_dns_transaction(self, tx):
        """Check if transaction contains DNS record information using Squawker protocol with SATORI"""
        try:
            # Check if it's an asset transfer
            if 'vout' not in tx or 'vin' not in tx:
                return False

            # Get the sending address from vin
            vin_addresses = []
            for vin in tx['vin']:
                prev_tx = self.rpc.getrawtransaction(vin['txid'], True)
                vin_vout = prev_tx['vout'][vin['vout']]
                if 'addresses' in vin_vout['scriptPubKey']:
                    vin_addresses.extend(vin_vout['scriptPubKey']['addresses'])

            # Track SATORI transfers
            satori_transfers = []
            
            # Get receiving addresses and check for SATORI transfers
            for vout in tx['vout']:
                if 'scriptPubKey' in vout and 'addresses' in vout['scriptPubKey']:
                    vout_addresses = vout['scriptPubKey']['addresses']
                    
                    # Check for asset transfer
                    if 'asset' in vout:
                        asset_info = vout['asset']
                        if (asset_info.get('name') == self.dns_asset and 
                            float(asset_info.get('amount', 0)) == self.dns_amount):
                            # Found a 1 SATORI transfer
                            satori_transfers.append({
                                'addresses': vout_addresses,
                                'amount': float(asset_info['amount'])
                            })

            # Check if it's a self-transfer of exactly 1 SATORI
            valid_satori_transfer = False
            for transfer in satori_transfers:
                if (any(addr in transfer['addresses'] for addr in vin_addresses) and 
                    transfer['amount'] == self.dns_amount):
                    valid_satori_transfer = True
                    break
            
            if not valid_satori_transfer:
                return False

            # Check for IPFS message in transaction
            if 'ipfs_op_return' in tx:
                return True

            # Fallback: check for OP_RETURN data
            for vout in tx['vout']:
                if ('scriptPubKey' in vout and 
                    'asm' in vout['scriptPubKey'] and 
                    vout['scriptPubKey']['asm'].startswith('OP_RETURN')):
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking DNS transaction: {str(e)}")
            return False
        
    def extract_ipfs_hash(self, tx):
        """Extract IPFS hash from Squawker protocol transaction"""
        try:
            # The IPFS hash should be in the ipfs_op_return field
            if 'ipfs_op_return' in tx:
                ipfs_hash = tx['ipfs_op_return']
                # Remove any 'ipfs:' prefix if present
                if ipfs_hash.startswith('ipfs:'):
                    ipfs_hash = ipfs_hash[5:]
                return ipfs_hash
            
            # Fallback: look through vout for OP_RETURN data
            for vout in tx['vout']:
                if 'scriptPubKey' in vout and 'asm' in vout['scriptPubKey']:
                    asm = vout['scriptPubKey']['asm']
                    if asm.startswith('OP_RETURN'):
                        parts = asm.split()
                        if len(parts) > 1:
                            hex_data = parts[1]
                            data = bytes.fromhex(hex_data).decode('utf-8')
                            if data.startswith('ipfs:'):
                                return data[5:]
                            # If it looks like a raw IPFS hash, return it
                            if len(data) == 46 and data.startswith('Qm'):
                                return data
                            
            raise ValueError("No IPFS hash found in transaction")
            
        except Exception as e:
            self.logger.error(f"Error extracting IPFS hash: {str(e)}")
            raise
        
    def fetch_dns_record(self, ipfs_hash):
        """Fetch DNS record from IPFS"""
        dns_data = self.ipfs_client.cat(ipfs_hash)
        return json.loads(dns_data)
        
    def get_sender_address(self, tx):
        """Extract the sender's address from the transaction"""
        if 'vin' in tx:
            for vin in tx['vin']:
                prev_tx = self.rpc.getrawtransaction(vin['txid'], True)
                vin_vout = prev_tx['vout'][vin['vout']]
                if 'addresses' in vin_vout['scriptPubKey']:
                    # Return the first address (sender)
                    return vin_vout['scriptPubKey']['addresses'][0]
        raise ValueError("Could not determine sender address")

    def update_bind_zone(self, dns_record, sender_address):
        """Update BIND zone with new DNS record using sender's address as subdomain"""
        update = dns.update.Update(self.zone_name)
        
        if 'type' in dns_record and 'data' in dns_record:
            record_type = dns_record['type']
            data = dns_record['data']
            
            # Create subdomain in format: <public_address>.evr.badguyty.com
            subdomain = f"{sender_address}.evr"
            
            # Add new record
            update.add(subdomain, 300, record_type, data)
            
            try:
                # Send update to BIND server
                dns.query.tcp(update, self.bind_server)
                self.logger.info(f"Successfully added {subdomain}.{self.zone_name} pointing to {data}")
            except Exception as e:
                self.logger.error(f"Failed to update BIND: {str(e)}")

def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    bind_server = os.getenv('BIND_SERVER')
    zone_name = os.getenv('ZONE_NAME')
    
    # Add default port for Evermore (different from Ravencoin's default 8766)
    watcher = EvermoreWatcher(
        rpc_user=config.RPC_USER,
        rpc_password=config.RPC_PASSWORD,
        rpc_host=config.RPC_HOST,
        rpc_port=config.RPC_PORT or 9766,
        bind_server=bind_server,
        zone_name=zone_name
    )
    print("Starting watcher")
    watcher.watch_blocks()

if __name__ == "__main__":
    main()