import asyncio, re, time, xml.etree.ElementTree, urllib.parse, json, random, html, sys
import aiohttp, qrcode

USERAGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/601.6.17 (KHTML, like Gecko) Version/9.1.1 Safari/601.6.17'

async def wechat_process(client, loop):
    deviceid = f'e{random.randrange(10**15):015d}'
    params = f'appid=wx782c26e4c19acffb&fun=new&lang=zh_CN&_={int(time.time())}'
    async with client.get('https://login.weixin.qq.com/jslogin', params=params) as resp:
        pattern = 'window.QRLogin.code = (\\d+); window.QRLogin.uuid = "(.+?)";'
        code, uuid = re.fullmatch(pattern, await resp.text('utf8')).groups()
        assert code == '200', f'Wrong code: {code}'
    qr = qrcode.QRCode(border=1)
    qr.add_data('https://login.weixin.qq.com/l/' + uuid)
    print('\x1b[m\n'.join(''.join('\x1b[40m  ' if j else '\x1b[47m  ' for j in i) for i in qr.get_matrix()) + '\x1b[m')
    params = f'tip=1&uuid={uuid}&_={int(time.time())}'
    async with client.get('https://login.weixin.qq.com/cgi-bin/mmwebwx-bin/login', params=params) as resp:
        code, = re.fullmatch('window.code=(\\d+);', await resp.text('utf8')).groups()
        assert code == '201', f'Wrong Code: {code}'
    params = f'tip=0&uuid={uuid}&_={int(time.time())}'
    async with client.get('https://login.weixin.qq.com/cgi-bin/mmwebwx-bin/login', params=params) as resp:
        pattern = 'window.code=(\\d+);\nwindow.redirect_uri="(.+?)";'
        code, redirect_uri = re.fullmatch(pattern, await resp.text('utf8')).groups()
        base_uri = redirect_uri[:redirect_uri.rfind('/')]
        assert code == '200', f'Wrong Code: {code}'
    async with client.get(redirect_uri+'&fun=new') as resp:
        root = xml.etree.ElementTree.fromstring(await resp.text('utf8'))
        message = root.find('./message').text
        assert message == 'OK', 'Message is ' + message
        skey = root.find('./skey').text
        wxsid = root.find('./wxsid').text
        wxuin = root.find('./wxuin').text
        pass_ticket = root.find('./pass_ticket').text
        base_request = dict(Uin=int(wxuin), Sid=wxsid, Skey=skey, DeviceID=deviceid)
    json_post = lambda api, params, data: client.post(base_uri + api, params=params, headers={'Content-Type': 'application/json; charset=UTF-8'}, data=json.dumps(data, ensure_ascii=False))
    data = dict(BaseRequest=base_request)
    params = f'pass_ticket={pass_ticket}&skey={skey}&r={int(time.time())}'
    async with json_post('/webwxinit', params, data) as resp:
        data = json.loads(await resp.text('utf8'))
        assert data['BaseResponse']['Ret'] == 0, str(data['BaseResponse'])
        #contacts = dict((i['UserName'], i) for i in data['ContactList'])
        SyncKey = data['SyncKey']
        synckey = '|'.join(f'{i["Key"]}_{i["Val"]}' for i in SyncKey['List'])
        user = data['User']
    params = f'lang=zh_CN&pass_ticket={pass_ticket}'
    data = dict(BaseRequest=base_request, Code=3, FromUserName=user['UserName'], ToUserName=user['UserName'], ClientMsgId=int(time.time()))
    async with json_post('/webwxstatusnotify', params, data) as resp:
        data = json.loads(await resp.text('utf8'))
        assert data['BaseResponse']['Ret'] == 0, str(data['BaseResponse'])
    try:
        params = f'pass_ticket={pass_ticket}&skey={skey}&r={int(time.time())}'
        async with json_post('/webwxgetcontact', params, {}) as resp:
            data = json.loads(await resp.text('utf8'))
            assert data['BaseResponse']['Ret'] == 0, str(data['BaseResponse'])
            contacts = dict((i['UserName'], i) for i in data['MemberList'])
    except Exception as ex:
        print('Load contact list failed.', ex)
        contacts = {}
    success = False
    syncpattern = re.compile('window.synccheck={retcode:"(\\d+)",selector:"(\\d+)"}')
    for synchost in ('webpush.weixin.qq.com', 'webpush2.weixin.qq.com', 'webpush.wechat.com', 'webpush1.wechat.com', 'webpush2.wechat.com', 'webpush1.wechatapp.com'):
        params = f'r={int(time.time())}&sid={wxsid}&uin={wxuin}&skey={skey}&deviceid={deviceid}&synckey={synckey}&_={int(time.time())}'
        try:
            with aiohttp.Timeout(10):
                async with client.get(f'https://{synchost}/cgi-bin/mmwebwx-bin/synccheck', params=params) as resp:
                    code, selector = syncpattern.fullmatch(await resp.text('utf8')).groups()
                    success = True
                    break
        except Exception:
            pass
    assert success, 'No host is available'
    async def getcontact(s, group=None):
        if s == user['UserName']:
            return user
        group = dict((i['UserName'], i) for i in group['MemberList']) if group else {}
        if s in contacts:
            c = contacts[s]
        elif s in group:
            c = group[s]
        else:
            params = f'type=ex&r={int(time.time())}&pass_ticket={pass_ticket}'
            data = dict(BaseRequest=base_request, Count=1, List=[dict(UserName=s, EncryChatRoomId='')])
            async with json_post('/webwxbatchgetcontact', params, data) as resp:
                data = json.loads(await resp.text('utf8'))
                assert data['BaseResponse']['Ret'] == 0, str(data['BaseResponse'])
                c = data['ContactList'][0]
                contacts[c['UserName']] = c
        return c
    emoji = re.compile('<span class="emoji emoji(.+?)"></span>')
    def getname(c):
        name = c.get('RemarkName', None) or c['NickName']
        m = emoji.search(name)
        while m:
            start, end = m.span()
            name = name[:start] + chr(int(m.group(1), 16)) + name[end:]
            m = emoji.search(name)
        return name
    async def sendmsg(cmd):
        if not cmd.strip(): return
        name, content = cmd.strip().split(' ', 1)
        found = None
        for c in contacts.values():
            if getname(c) == name:
                found = c
                break
        if found is None:
            print('Unknown user', name)
            return
        msgid = f'{int(time.time()*1000)}{random.randrange(10**4):04d}'
        data = dict(BaseRequest=base_request, Msg=dict(Type=1, Content=content, FromUserName=user['UserName'], ToUserName=c['UserName'], LocalID=msgid, ClientMsgId=msgid))
        async with json_post('/webwxsendmsg', f'pass_ticket={pass_ticket}', data) as resp:
            data = json.loads(await resp.text('utf8'))
    def handle_stdin():
        loop.create_task(sendmsg(sys.stdin.readline()))
    loop.add_reader(sys.stdin, handle_stdin)
    while True:
        check_msg = False
        if code != '0':
            print('Quit with code', code)
            break
        if selector != '0':
            print('Cmd', selector)
            params = f'sid={wxsid}&skey={skey}&pass_ticket={pass_ticket}'
            data = dict(BaseRequest=base_request, SyncKey=SyncKey, rr=~int(time.time()))
            async with json_post('/webwxsync', params, data) as resp:
                data = json.loads(await resp.text('utf8'))
                code = data['BaseResponse']['Ret']
                if code != 0:
                    print('Quit with code', code)
                    break
                SyncKey = data['SyncKey']
                synckey = '|'.join(f'{i["Key"]}_{i["Val"]}' for i in SyncKey['List'])
            groupsend = re.compile('(@.+):<br/>')
            for msg in data['AddMsgList']:
                msgtype = msg['MsgType']
                fromc = await getcontact(msg['FromUserName'])
                fromname = getname(fromc)
                toname = getname(await getcontact(msg['ToUserName']))
                content = html.unescape(msg['Content'])
                msgid = msg['MsgId']
                m = groupsend.match(content)
                if m and 'MemberList' in fromc:
                    start, end = m.span()
                    memberc = await getcontact(m.group(1), fromc)
                    membername = getname(memberc)
                    content = content[end:]
                    print(msgtype, fromname, f'({membername})', '-->', toname, content)
                else:
                    print(msgtype, fromname, '-->', toname, content)
        params = f'r={int(time.time())}&sid={wxsid}&uin={wxuin}&skey={skey}&deviceid={deviceid}&synckey={synckey}&_={int(time.time())}'
        async with client.get(f'https://{synchost}/cgi-bin/mmwebwx-bin/synccheck', params=params) as resp:
            code, selector = syncpattern.fullmatch(await resp.text('utf8')).groups()

def main():
    loop = asyncio.get_event_loop()
    with aiohttp.ClientSession(headers={'User-Agent': USERAGENT, 'Accept-Encoding': 'deflate, gzip'}) as client:
        loop.run_until_complete(wechat_process(client, loop))
    loop.close()

if __name__ == '__main__':
    main()
