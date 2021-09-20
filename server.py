#!/bin/env python3

import argparse
import asyncio
import logging
import socket
import urllib.parse
from typing import Dict


class bemfaTcpAPI:

    def __init__(self, host: str, port: int, api_key: str, topic: str, keep_alive_interval=60):
        self.host = host
        self.port = port
        self.api_key = api_key
        self.topic = topic
        self.keep_alive_interval = keep_alive_interval

        self.reader = None
        self.writer = None
        self.keepalive_task = None

    async def connect(self):

        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        message = "cmd=1&uid={uid}&topic={topic}\r\n".format(uid=self.api_key, topic=self.topic)
        self.writer.write(message.encode())
        self.keepalive_task = asyncio.create_task(self.keepalive())
        while True:
            line = await self.reader.readline()
            if not line:
                break
            line = line.decode().strip()
            logging.info("Message incoming: %s", line)
            qs = urllib.parse.parse_qs(line)
            if qs['cmd'][0] == '0':  # ping echo reply
                continue
            yield qs
        self.writer = None
        self.reader = None

    async def keepalive(self):
        while self.writer:
            self.writer.write('ping\r\n'.encode())
            await asyncio.sleep(self.keep_alive_interval)


def send_wake_on_lan_packet(ethernet_address, broadcast_ip, wol_port=9):
    ethernet_address = ethernet_address.replace('-', '').replace(':', '')
    ethernet_address = bytes.fromhex(ethernet_address)

    assert(len(ethernet_address) == 6)

    # Build magic packet
    msg = b'\xff' * 6 + ethernet_address

    # Send packet to broadcast address using UDP port 9
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(msg, (broadcast_ip, wol_port))
    s.close()


async def start_server(api, mac_address: str, broadcast_ip: str):
    async for message in api.connect():
        print(message)
        if 'msg' in message and message['msg'][0] == 'on':
            send_wake_on_lan_packet(mac_address, broadcast_ip)


def main():
    parser = argparse.ArgumentParser('PowerControl virtual device daemon')
    parser.add_argument('--api-key', type=str, required=True, help='the bemfa api key')
    parser.add_argument('--topic', type=str, required=True, help='the bemfa topic')
    parser.add_argument('--mac', type=str, required=True, help='the mac address of your network card to wake up')
    parser.add_argument('--broadcast', type=str, required=True, help='the broadcast ip of your network')
    args = parser.parse_args()

    api = bemfaTcpAPI('bemfa.com', '8344', args.api_key, args.topic)

    logging.basicConfig(level=logging.INFO)

    asyncio.run(start_server(api, mac_address=args.mac, broadcast_ip=args.broadcast))


if __name__ == '__main__':
    main()
