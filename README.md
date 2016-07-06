python-wechat
===========

A simple Python wechat web client implemented in Python 3.6 asyncio/aiohttp.

Overview
-----------

Wechat web client is a simple message exchanger based on http protocol. Just run this program and scan the QRCode with your mobile wechat. It will sync all messages by asynchronous web requests. You can build more interesting features based on this.

Requirements
-----------

    $ sudo pip-3.6 install aiohttp qrcode

Usage
-----------

Run this program with no parameters, scan the QRCode with mobile wechat, and then wait for incoming messages. To send message, just type the username and message in standard input. For example, type "Justin hello, the world" will send "hello, the world" to user with name "Justin"

