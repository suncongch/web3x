from asyncio.windows_events import NULL
from datetime import datetime, timezone, timedelta
from importlib.abc import ExecutionLoader
import re
from tkinter import EXCEPTION
import requests
import urllib
from random import randint, random
from postImage import thisSubUrl,janSubUrl,netflixSubUrl,justSubUrl
from flask import Flask, Response
from ini import *
from sub import *

githubConfig = "data/githubConfig.txt"
netflixConfig = "data/netflixConfig.txt"

excloudeConditon = r'游戏|流量|🐯|时间|印度|越南|法国|德国|澳洲|套餐|IPv6|重置|欢迎|每天|日本 1|土耳其|1-三网优化|2-三网优化|3-三网优化|香港 BGP|美国 \[ 0.3x \]|美国区域|\[ 0.5x \]|隧道香港|英国区域|电信优化'

includeCondition = r'日本 1|日本 2|日本 3|日本 1\s*[ IPv6 ]|香港|新加坡 1$|新加坡 1\s*[ IPv6 ]|新加坡 2 \[ 推荐 \]$|新加坡 2\s*[ IPv6 ]|美国.*|台湾$|台湾\s*[ IPv6 ]|(?<=韩国|日本|狮城).*自动运维|(?<=台湾区域)'

netflixIncludeCondition = r'日本 1|日本 2|日本 3|日本 1\s*[ IPv6 ]|香港|新加坡 1$|新加坡 1\s*[ IPv6 ]|新加坡 2 \[ 推荐 \]$|新加坡 2\s*[ IPv6 ]|香港|台湾$|台湾\s*[ IPv6 ]|'

netFliexExcloudeConditon = '游戏|流量|时间|印度|美国|越南|法国|加州|德国|澳洲|套餐|重置|欢迎|每天|日本 1|订阅|联系|土耳其|英国'

urlHeade = 'http://andysun.cool:25500/sub?'
#urlHeade = 'https://sub.xeton.dev/sub?'
#urlHeade = 'https://api.wcc.best/sub?'


githubUrl = 'https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/config/ACL4SSR_Online_Mini_NoAuto.ini'

nodeMod = r'''
add_emoji=true
remove_old_emoji=true
emoji=(香港|HK|Hong Kong),🇭🇰
emoji=(日本|川日|东京|大阪|泉日|埼玉|JP|Japan),🇯🇵
emoji=(美国|波特兰|达拉斯|俄勒冈|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥|US|United States),🇺🇸
emoji=(台湾|新北|彰化|TW|Taiwan),🇹🇼
emoji=(新加坡|坡|狮城|狮城|SG|Singapore),🇸🇬
emoji=(KR|Korea|KOR|首尔|韩国|韩|韓),🇰🇷
emoji=(DE|Germany|DEU|德|德国),🇩🇪
emoji=(IN|India|IND|印度),🇮🇳
emoji=(CA|Canada|CAN|加拿大),🇨🇦
emoji=(LU|LUX|卢森堡|盧森堡),🇱🇺
emoji=(RU|RUS|俄罗斯|俄),🇷🇺
emoji=(TR|TUR|土耳其),🇹🇷
emoji=(GB|GBR|UK|英国|英),🇬🇧
emoji=(AR|ARG|阿根廷),🇦🇷
emoji=(BR|BRA|巴西),🇧🇷
emoji=(AU|AUS|澳大利亚|澳),🇦🇺
emoji=(AE|UAE|阿联酋|阿拉伯联合酋长国),🇦🇪
emoji=(PL|POL|波兰),🇵🇱
emoji=(FR|FRA|法国),🇫🇷
rename_node=新加坡@狮城
rename_node=2\ 倍扣费节点@备用
rename_node=  \[ h4 \]@
rename_node=  \ \[ 推荐 \]@
rename_node=  \ \[\ 高速\ \]@
rename_node=  (\d+)@$1
rename_node=  狮城\ (\d)\ $@狮城 $1   wifi 推荐
rename_node=  日本\ (\d)\ $@日本 $1   wifi 推荐
rename_node=  狮城\ (\d)\ \[(.*)Inter2\ \]$@狮城 $1   wifi 推荐
rename_node=  日本\ (\d)\ \[(.*)Inter2\ \]$@日本 $1   wifi 推荐
rename_node=  韩国.*?/(SK|KT)区域(\d+)节点$@韩国区域$2-$1节点
rename_node= -解锁Netflix@🍿

rename_node=hysteria2-vultr.andysun.cool-42426@🇸🇬 vultr
rename_node=andy@🇸🇬 vultr

rename_node=\ h12@
rename_node=  \[ IPv6 \]@  📶 流量  \[IPv6\]
rename_node=  \ \[ 0.5x \]@
'''
nodeMod_ios_anndroid = r'''
add_emoji=true
remove_old_emoji=true
emoji=(香港|HK|Hong Kong),🇭🇰
emoji=(日本|川日|东京|大阪|泉日|埼玉|JP|Japan),🇯🇵
emoji=(美国|波特兰|达拉斯|俄勒冈|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥|US|United States),🇺🇸
emoji=(台湾|新北|彰化|TW|Taiwan),🇹🇼
emoji=(新加坡|坡|狮城|狮城|SG|Singapore),🇸🇬
emoji=(KR|Korea|KOR|首尔|韩国|韩|韓),🇰🇷
emoji=(DE|Germany|DEU|德|德国),🇩🇪
emoji=(IN|India|IND|印度),🇮🇳
emoji=(CA|Canada|CAN|加拿大),🇨🇦
emoji=(LU|LUX|卢森堡|盧森堡),🇱🇺
emoji=(RU|RUS|俄罗斯|俄),🇷🇺
emoji=(TR|TUR|土耳其),🇹🇷
emoji=(GB|GBR|UK|英国|英),🇬🇧
emoji=(AR|ARG|阿根廷),🇦🇷
emoji=(BR|BRA|巴西),🇧🇷
emoji=(AU|AUS|澳大利亚|澳),🇦🇺
emoji=(AE|UAE|阿联酋|阿拉伯联合酋长国),🇦🇪
emoji=(PL|POL|波兰),🇵🇱
emoji=(FR|FRA|法国),🇫🇷
rename_node=新加坡@狮城
rename_node=  \[ h4 \]@
rename_node=  \ \[ 推荐 \]@
rename_node=  \ \[ 高速 \]@
rename_node=  (\d+)@$1
rename_node=  狮城\s(\d)\ $@狮城 $1   🛜 推荐
rename_node=  日本\ (\d)\ $@日本 $1   🛜 推荐

rename_node=  狮城\ (\d)\ \[(.*)Inter2\ \]$@狮城 $1   wifi 推荐
rename_node=  日本\ (\d)\ \[(.*)Inter2\ \]$@日本 $1   wifi 推荐
rename_node=  韩国.*?/(SK|KT)区域(\d+)节点$@韩国区域$2-$1节点
rename_node= -解锁Netflix@🍿

rename_node=  \[ IPv6 \]@  📶 流量  \[IPv6\]
rename_node=  \ \[ 0.5x \]@
'''

r"""
rename_node=  虎云高可用 1 @日本 ins/yt 📱推荐 1
rename_node=  虎云高可用 2 @狮城 ins/yt 📱推荐 2 
rename_node=  虎云高可用 3 @狮城 ins/yt 📱推荐 3 
rename_node=  日本 1@ 日本 💻推荐 1 
rename_node=  日本 2@ 日本 💻推荐 2 

rename_node=  新加坡 1@ 狮城 💻推荐 1 
rename_node=  新加坡 2 \[ 推荐 \]@ 狮城 💻推荐 2 
rename_node=  新加坡 2 \[ 高速 \]@ 狮城 📱流量 1 
"""
port='''mixed-port: 7890
allow-lan: true
bind-address: '*'
mode: rule
log-level: info
external-controller: '127.0.0.1:9090'
secret: huyun_password
tcp-concurrent: true
ipv6: true
clash-for-android:
    append-system-dns: false
dns:
    enable: true
    ipv6: true
    default-nameserver: [223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    fake-ip-range: 198.18.0.1/16
    use-hosts: true
    proxy-server-nameserver: ['https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query', 'https://120.53.53.53/dns-query', 'tls://dot.pub', 'tls://120.53.53.53', 'tls://dns.alidns.com', 223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    nameserver: ['https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query', 'https://120.53.53.53/dns-query', 'tls://dot.pub', 'tls://120.53.53.53', 'tls://dns.alidns.com', 223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    fallback: ['https://doh.dns.sb/dns-query', 'https://dns.cloudflare.com/dns-query', 'https://dns.twnic.tw/dns-query', 'tls://8.8.4.4:853', 'https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query', 'https://120.53.53.53/dns-query', 'tls://dot.pub', 'tls://120.53.53.53', 'tls://dns.alidns.com', 223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    fallback-filter: { geo: [240.0.0.0/4, 0.0.0.0/32, 127.0.0.1/32, 61.160.148.90/32, 124.236.16.201/32, 182.43.124.6/32, 106.74.25.198/32, 120.222.19.204/32, 221.228.32.13/32, 211.137.117.149/32, 36.135.82.110/32, 183.203.36.36/32, 111.28.0.32/32, 117.156.25.11/32, 120.204.204.201/32, 120.209.204.204/32, 211.138.218.190/32, 183.252.183.9/32, 117.187.10.42/32, 218.203.122.98/32, 221.180.160.221/32, 111.31.192.110/32, 221.130.39.3/32, 120.209.204.20/32, 218.201.25.129/32, 211.139.145.129/32, 36.138.129.47/32, 112.54.50.50/32, 111.22.226.1/32, 111.63.132.170/32, 111.44.246.131/32, 112.17.14.211/32, 111.22.226.1/32, 47.92.198.202/32] }
'''

FIClashPort = """mixed-port: 7890
allow-lan: true
bind-address: '*'
mode: rule
log-level: info
external-controller: '127.0.0.1:9090'
secret: huyun_password
tcp-concurrent: true
ipv6: true
clash-for-android:
append-system-dns: false
dns:
    enable: true
    ipv6: true
    default-nameserver: [223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    fake-ip-range: 198.18.0.1/16
    use-hosts: true
    proxy-server-nameserver: ['https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query', 'https://120.53.53.53/dns-query', 'tls://dot.pub', 'tls://120.53.53.53', 'tls://dns.alidns.com', 223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    nameserver: ['https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query', 'https://120.53.53.53/dns-query', 'tls://dot.pub', 'tls://120.53.53.53', 'tls://dns.alidns.com', 223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    fallback: ['https://doh.dns.sb/dns-query', 'https://dns.cloudflare.com/dns-query', 'https://dns.twnic.tw/dns-query', 'tls://8.8.4.4:853', 'https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query', 'https://120.53.53.53/dns-query', 'tls://dot.pub', 'tls://120.53.53.53', 'tls://dns.alidns.com', 223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    fallback-filter: { geo: [240.0.0.0/4, 0.0.0.0/32, 127.0.0.1/32, 61.160.148.90/32, 124.236.16.201/32, 182.43.124.6/32, 106.74.25.198/32, 120.222.19.204/32, 221.228.32.13/32, 211.137.117.149/32, 36.135.82.110/32, 183.203.36.36/32, 111.28.0.32/32, 117.156.25.11/32, 120.204.204.201/32, 120.209.204.204/32, 211.138.218.190/32, 183.252.183.9/32, 117.187.10.42/32, 218.203.122.98/32, 221.180.160.221/32, 111.31.192.110/32, 221.130.39.3/32, 120.209.204.20/32, 218.201.25.129/32, 211.139.145.129/32, 36.138.129.47/32, 112.54.50.50/32, 111.22.226.1/32, 111.63.132.170/32, 111.44.246.131/32, 112.17.14.211/32, 111.22.226.1/32, 47.92.198.202/32] }"""

clashConfigBackUp = '''mixed-port: 7890
allow-lan: true
bind-address: '*'
mode: rule
log-level: info
external-controller: '127.0.0.1:9090'
hosts:
    mtalk.google.com: 108.177.125.188
    services.googleapis.cn: 74.125.203.94
    raw.githubusercontent.com: 151.101.76.133
dns:
    enable: true
    listen: '0.0.0.0:53'
    ipv6: true
    default-nameserver: [223.5.5.5, 114.114.114.114, 8.8.8.8]
    enhanced-mode: fake-ip
    fake-ip-range: 198.18.0.1/16
    fake-ip-filter: ['*.lan', '*.linksys.com', '*.linksyssmartwifi.com', swscan.apple.com, mesu.apple.com, '*.msftconnecttest.com', '*.msftncsi.com', 'time.*.com', 'time.*.gov', 'time.*.edu.cn', 'time.*.apple.com', 'time1.*.com', 'time2.*.com', 'time3.*.com', 'time4.*.com', 'time5.*.com', 'time6.*.com', 'time7.*.com', 'ntp.*.com', 'ntp.*.com', 'ntp1.*.com', 'ntp2.*.com', 'ntp3.*.com', 'ntp4.*.com', 'ntp5.*.com', 'ntp6.*.com', 'ntp7.*.com', '*.time.edu.cn', '*.ntp.org.cn', +.pool.ntp.org, time1.cloud.tencent.com, +.music.163.com, '*.126.net', musicapi.taihe.com, music.taihe.com, songsearch.kugou.com, trackercdn.kugou.com, '*.kuwo.cn', api-jooxtt.sanook.com, api.joox.com, joox.com, +.y.qq.com, +.music.tc.qq.com, aqqmusic.tc.qq.com, +.stream.qqmusic.qq.com, '*.xiami.com', +.music.migu.cn, +.srv.nintendo.net, +.stun.playstation.net, 'xbox.*.microsoft.com', +.xboxlive.com, localhost.ptlogin2.qq.com, proxy.golang.org, 'stun.*.*', 'stun.*.*.*', '+.stun.*.*.*.*', heartbeat.belkin.com, '*.linksys.com', '*.linksyssmartwifi.com', '*.router.asus.com', mesu.apple.com, swscan.apple.com, swquery.apple.com, swdownload.apple.com, swcdn.apple.com, swdist.apple.com, lens.l.google.com, stun.l.google.com, +.nflxvideo.net, '*.square-enix.com', '*.finalfantasyxiv.com', '*.ffxiv.com', '*.mcdn.bilivideo.cn']
    nameserver: ['https://doh.pub/dns-query', 'https://doh.dns.sb/dns-query', 'https://dns.adguard.com/dns-query', 'https://cdn-doh.ssnm.xyz/dns-query', 223.5.5.5, 180.76.76.76, 119.29.29.29, 117.50.11.11, 117.50.10.10, 114.114.114.114, 'https://dns.alidns.com/dns-query', 'https://doh.360.cn/dns-query']
    fallback: ['https://dns.quad9.net:5053/dns-query', 'https://dns-unfiltered.adguard.com/dns-query', 'https://doh.opendns.com/dns-query', 'https://1.0.0.1/dns-query', 'https://public.dns.iij.jp/dns-query', 'https://dns.twnic.tw/dns-query', 8.8.8.8, 1.1.1.1, 'tls://dns.rubyfish.cn:853', 'tls://1.0.0.1:853', 'tls://dns.google:853', 'https://dns.rubyfish.cn/dns-query', 'https://cloudflare-dns.com/dns-query', 'https://dns.google/dns-query']
    fallback-filter: { geoip: true, ipcidr: [0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.0.2.0/24, 192.88.99.0/24, 192.168.0.0/16, 198.18.0.0/15, 198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/4, 240.0.0.0/4, 255.255.255.255/32], domain: [+.google.com, +.facebook.com, +.youtube.com, +.freegfw.top, +.gogocloud.top, +.tgcloud.top, +.githubusercontent.com, +.googlevideo.com] }

'''

clashConfig = """mixed-port: 7890
allow-lan: true
bind-address: '*'
mode: rule
log-level: info
external-controller: '127.0.0.1:9090'
tcp-concurrent: true
ipv6: true
clash-for-android:
    append-system-dns: false
dns:
    enable: true
    ipv6: true
    default-nameserver: [223.5.5.5, 119.29.29.29, 180.76.76.76, 223.6.6.6, 119.28.28.28]
    fake-ip-range: 198.18.0.1/16
    use-hosts: true
    nameserver: ['udp://146.190.131.173:55553', 'udp://192.155.81.6:1053', 'tcp://146.190.131.173:55553', 'tcp://192.155.81.6:1053']
    fallback: ['https://doh.pub/dns-query', 'https://120.53.53.53/dns-query', 'tls://dot.pub', 'tls://120.53.53.53', 'https://dns.alidns.com/dns-query', 'tls://dns.alidns.com']
    fallback-filter: { geo: [240.0.0.0/4, 0.0.0.0/32, 127.0.0.1/32, 61.160.148.90/32, 124.236.16.201/32, 182.43.124.6/32, 106.74.25.198/32, 120.222.19.204/32, 221.228.32.13/32, 211.137.117.149/32, 36.135.82.110/32, 183.203.36.36/32, 111.28.0.32/32, 117.156.25.11/32, 120.204.204.201/32, 120.209.204.204/32, 211.138.218.190/32, 183.252.183.9/32, 117.187.10.42/32, 218.203.122.98/32, 221.180.160.221/32, 111.31.192.110/32, 221.130.39.3/32, 120.209.204.20/32, 218.201.25.129/32, 211.139.145.129/32, 36.138.129.47/32, 112.54.50.50/32, 111.22.226.1/32, 111.63.132.170/32, 111.44.246.131/32, 112.17.14.211/32, 111.22.226.1/32, 47.92.198.202/32] }
"""

def v2rayReturn(token):
    urlHeade = 'https://api.wcc.best/sub?'

    if token == "just":
        temSubscribeUrl = justSubUrl[0]
        print('justPost')
    elif token == "jan":
        temSubscribeUrl = janSubUrl[0]
        print('janPost')
    elif token == "this":
        temSubscribeUrl = thisSubUrl[0]
        print("thisPost")
    
    selfUrl = 'http://cloud.andysun.cool:9001/iniMobile'
    selfUrl+='?index='+str(randint(1,50))

    urlParameter = ['target=mixed&url=',temSubscribeUrl,
                    '&include=',includeCondition,
                    '&config=',selfUrl,
                    '&remover_emoji = false&filename=Andysun_'+token]
    
    urlFull  = urlHeade
    urlFull += urlParameter[0] + urllib.parse.quote(urlParameter[1])
    urlFull += urlParameter[2] + urllib.parse.quote(urlParameter[3])
    urlFull += urlParameter[4] + urllib.parse.quote(urlParameter[5])

    x = requests.get(urlFull).text
    
    return x

def c19sReturn():
    urlHeade = 'https://api.wcc.best/sub?'
    subscribeUrl = "https://jmssub.net/members/getsub.php?service=80064&id=e56a34c3-a577-4d3b-8879-4ce573a5899c"
    urlParameter = ['target=ss&url=',subscribeUrl,'&exclude=','(游戏|流量|时间|印度|加州|法国|德国|节点|澳洲|套餐|重置)','&config=','http://cloud.andysun.cool:9001/ini','&remover_emoji = false']
    
    urlFull = urlHeade+urlParameter[0]+urllib.parse.quote(urlParameter[1])
    return requests.get(urlFull).text

def clashReturn(token,device,vless=False):
    if device in ("Shadowrocket","Android"):
        selfUrl = 'http://cloud.andysun.cool:9001/iniMobile'
    else:
        selfUrl = 'http://cloud.andysun.cool:9001/ini'
    
    temSubscribeUrl = None

    if token == "just":
        temSubscribeUrl = justSubUrl
        print('justPost')
    elif token == "jan":
        temSubscribeUrl = janSubUrl[:2]
        print('janPost')
    elif token == "this":
        temSubscribeUrl = thisSubUrl[:2]
        print("thisPost")

    if vless:
        temSubscribeUrl=temSubscribeUrl+'&type=vless'
    if token == "jut":
        selfUrl+='?index='+str(randint(1,50))

        urlParameter = ['target=clash&url=',temSubscribeUrl,
                        '&include=',includeCondition,
                        '&config=',selfUrl,
                        '&remover_emoji = false',
                        '&enable_cache = false']
        urlFull  = urlHeade
        urlFull += urlParameter[0] + urllib.parse.quote(urlParameter[1])
        urlFull += urlParameter[2] + urllib.parse.quote(urlParameter[3])
        urlFull += urlParameter[4] + urllib.parse.quote(urlParameter[5])
        urlFull += urlParameter[6] + urllib.parse.quote(urlParameter[7])
        response = makeResponse(urlFull,temName='Andysun_'+token)
        return response
    else:
        yamlFile = build_from_config(selfUrl,temSubscribeUrl)
        #save_yaml(yamlFile,"./test.yaml")
        return yaml_response(yamlFile,'Andysun_'+token,None)
    
def netflixReturn(token,device):
    
    if device in ("Shadowrocket","Android"):
        selfUrl = 'http://cloud.andysun.cool:9001/iniMobile'
    else:
        selfUrl = 'http://cloud.andysun.cool:9001/netflixIni'
    #selfUrl+='?index='+str(randint(1,50))
    print(selfUrl)
    print('heter')
    print(device)
    if token == "just":
        temSubscribeUrl = justSubUrl[:1]
        infoUrl = temSubscribeUrl[0]
    elif token == "jan":
        temSubscribeUrl = janSubUrl[:1]
        infoUrl = temSubscribeUrl[0]
    elif token == "this":
        temSubscribeUrl = janSubUrl
        infoUrl = janSubUrl[0]
    
    user_info = getUserInfo(infoUrl)
    print(user_info)
    yamlFile = build_from_config(selfUrl,temSubscribeUrl,auto_group=True)
    #save_yaml(yamlFile,"./test.yaml")
    return yaml_response(yamlFile,'Admin_'+token,user_info)
def iniReturn():
    urlHead = 'https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/config/ACL4SSR_Online_Mini_NoAuto.ini'
    f = open(githubConfig,'r',encoding='utf-8')
    returnText = f.read()
    f.close()

    return returnText + nodeMod

def iniReturn_mobile():
    urlHead = 'https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/config/ACL4SSR_Online_Mini_NoAuto.ini'
    f = open(githubConfig,'r',encoding='utf-8')
    returnText = f.read()
    f.close()

    return returnText + nodeMod_ios_anndroid
    
def netflixIniReturn():
    f = open(netflixConfig,'r',encoding='utf-8')
    returnText = f.read()
    f.close()
    return returnText + nodeMod

#废弃函数
def githubSaveTxt():
    try:
        urlHead = 'https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/config/ACL4SSR_Online_Mini_NoAuto.ini'
        x = requests.get(urlHead)
        if x.status_code == requests.codes.ok and x.text is not None:
            f = open(githubConfig,'w',encoding='utf-8')
            result = insert_string(x.text, "ruleset=🎯 全球直连", "ruleset=🎯 全球直连,https://raw.githubusercontent.com/suncongch/passWall/main/combine1\n")
            f.write(result)
            f.close()
            print("online config request success")
            return result
        else:
            f = open(githubConfig,'r',encoding='utf-8')
            returnText = f.read()
            f.close()
            print("127.0.0.1 - - online config request faile")
            return returnText
    except:
        f = open(githubConfig,'r',encoding='utf-8')
        returnText = f.read()
        f.close()
        print("127.0.0.1 - - online config request faile")
        return returnText
        pass
    
def insert_string(original_string, keyword, insertion_string):
    # 在原始字符串中查找关键字的位置
    index = original_string.find(keyword)

    # 如果找到关键字，则插入字符串
    if index != -1:
        # 切片操作，将插入字符串插入到关键字之后
        modified_string = original_string[:index] + insertion_string + original_string[index:]
        return modified_string
    else:
        # 如果找不到关键字，则返回原始字符串
        return original_string

def adminRetun(token,device,vless):
    if device in ("Shadowrocket","Android"):
        selfUrl = 'http://cloud.andysun.cool:9001/iniMobile'
    else:
        selfUrl = 'http://cloud.andysun.cool:9001/ini'
    #selfUrl+='?index='+str(randint(1,50))

    if token == "just":
        temSubscribeUrl = justSubUrl
        infoUrl = temSubscribeUrl[0]
    elif token == "jan":
        temSubscribeUrl = janSubUrl[:1]
        infoUrl = temSubscribeUrl[0]
    elif token == "this":
        temSubscribeUrl = janSubUrl
        infoUrl = janSubUrl[0]
    
    if vless:
        temSubscribeUrl = temSubscribeUrl + "?typt=vless"
    print(temSubscribeUrl)
    user_info = getUserInfo(infoUrl)
    if token == "jut":
        urlParameter = ['target=clash&url=',temSubscribeUrl,
                        '&filename=jiangzi&include=',includeCondition,
                        '&config=',selfUrl,
                        ]

        urlFull  = urlHeade
        urlFull += urlParameter[0] + urllib.parse.quote(urlParameter[1])
        urlFull += urlParameter[2] + urllib.parse.quote(urlParameter[3])
        urlFull += urlParameter[4] + urllib.parse.quote(urlParameter[5])
        response = makeResponse(urlFull,user_info,"Admin_"+token)

        return response
    else:
        print(user_info)
        yamlFile = build_from_config(selfUrl,temSubscribeUrl,auto_group=True)
        #save_yaml(yamlFile,"./test.yaml")
        return yaml_response(yamlFile,'Admin_'+token,user_info)

def getAllUserInfo():
    userInfos = {}
    for i in range(0,len(subscribe2025Url)):
        userInfos[i] = getUserInfo(subscribe2025Url[i])
    print(userInfos)

def makeResponse(temUrl, temValue=None, temName='Andysun'):
    try:
        r = requests.get(temUrl, timeout=30)
        # 不用 chunk 获取（一次性取全）
        r.raise_for_status()
        bytes_content = r.content # 保留原始字节，避免错误解码
        # 截断到 proxies (优先匹配 'proxies:'，否则退回 'proxies')
        pos = bytes_content.find(b'proxies:')
        if pos == -1:
            pos = bytes_content.find(b'proxies')
        if pos > -1:
            bytes_content = bytes_content[pos:]
        if isinstance(port, str):
            bytes_content = port.encode('utf-8') + bytes_content
    except requests.RequestException as e:
        print(f"Error fetching URL {temUrl}: {e}")
        bytes_content = b"Error fetching content."

    def stream():
        chunk_size = 8192  # 较小分块
        total = len(bytes_content)
        for i in range(0, total, chunk_size):
            yield bytes_content[i:i+chunk_size]

    # 如果是文本且确定 UTF-8，可改 mimetype 为 text/plain;charset=utf-8
    resp = Response(stream(), mimetype='text/plain;charset=utf-8')
    if temUrl is not None and temValue is not None:
        resp.headers['subscription-userinfo'] = temValue
    else:
        resp.headers['subscription-userinfo'] = 'update=' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    resp.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{temName}"
    # 不手动设置 Transfer-Encoding，交给服务器/WSGI
    return resp

def getUserInfo(temUrl):
    # 设置自定义 headers
    headers = {
        'User-Agent': 'ClashforWindows/0.20.39'
    }

    response = requests.get(temUrl,headers=headers)
    # 获取请求的 headers
    headers = response.headers
    return headers['subscription-userinfo']

def yaml_response(temYaml, filename: str, userinfo: str | None = None):
    yaml_text = yamlToStr(temYaml)
    def stream():
        chunk_size = 8192  # 较小分块
        data = yaml_text.encode("utf-8")  # ✅ 一次性转 bytes
        total = len(data)
        for i in range(0, total, chunk_size):
            yield data[i:i+chunk_size]

    # 如果是文本且确定 UTF-8，可改 mimetype 为 text/plain;charset=utf-8
    resp = Response(stream(), mimetype='text/plain;charset=utf-8')
    resp.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{filename}"
    if userinfo:
        resp.headers['subscription-userinfo'] = userinfo
    else:
        resp.headers['subscription-userinfo'] = 'update=' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    return resp
