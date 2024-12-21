$TTL    604800
@       IN      SOA     badguyty.com. admin.badguyty.com. (
                     2023051001         ; Serial
                         604800         ; Refresh
                          86400         ; Retry
                        2419200         ; Expire
                         604800 )       ; Negative Cache TTL
;
@       IN      NS      ns1.badguyty.com.
@       IN      A       127.0.0.1
ns1     IN      A       127.0.0.1 