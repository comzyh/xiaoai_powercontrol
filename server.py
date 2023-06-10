#!/bin/env python3

import argparse
import asyncio
import logging
import socket
import urllib.parse
from typing import AsyncGenerator, Optional

LOGGER = logging.getLogger('xiaoai_power_control')


class bemfaTcpAPI:

    def __init__(self, host: str, port: int, api_key: str, topic: str, keep_alive_interval=60):
        self.host: str = host
        self.port: int = port
        self.api_key = api_key
        self.topic = topic
        self.keep_alive_interval = keep_alive_interval

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.keepalive_task: Optional[asyncio.Task[None]] = None

    async def connect(self) -> AsyncGenerator[dict[str, list[str]], None]:
        while True:
            try:
                async for msg in self._connect():
                    yield msg
            except OSError:
                LOGGER.exception("Connection error")
                if self.keepalive_task:
                    self.keepalive_task.cancel()
                await asyncio.sleep(60)
                continue
            except Exception:
                LOGGER.exception("Unknown error")
                if self.keepalive_task:
                    self.keepalive_task.cancel()
                break

    async def _connect(self) -> AsyncGenerator[dict[str, list[str]], None]:

        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        message = "cmd=1&uid={uid}&topic={topic}\r\n".format(uid=self.api_key, topic=self.topic)
        self.writer.write(message.encode())
        self.keepalive_task = asyncio.create_task(self.keepalive())
        while True:
            line_bytes = await self.reader.readline()
            if not line_bytes:
                break
            line = line_bytes.decode().strip()
            LOGGER.info("Message incoming: %s", line)
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
    msg = b'\xff' * 6 + ethernet_address * 16

    # Send packet to broadcast address using UDP port 9
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(msg, (broadcast_ip, wol_port))
    s.close()


async def suspend_pc(host, key, state='Suspend'):
    command = "Add-Type -AssemblyName System.Windows.Forms;$PowerState = [System.Windows.Forms.PowerState]::{state};[System.Windows.Forms.Application]::SetSuspendState($PowerState, $false, $false);".format(
        state=state)
    args = ['-i', key, host, 'powershell', command]
    proc = await asyncio.create_subprocess_exec(
        'ssh', *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()
    LOGGER.info("Suspend: stdout: %s", stdout)
    LOGGER.info("Suspend: stderr: %s", stderr)


async def start_server(api, mac_address: str, broadcast_ip: str, host: str, key_file: str):
    async for message in api.connect():
        if 'msg' in message and message['msg'][0] == 'on':
            send_wake_on_lan_packet(mac_address, broadcast_ip)
        if 'msg' in message and message['msg'][0] == 'off':
            await suspend_pc(host, key_file)


def main():
    parser = argparse.ArgumentParser('PowerControl virtual device daemon')
    parser.add_argument('--api-key', type=str, required=True, help='the bemfa api key')
    parser.add_argument('--topic', type=str, required=True, help='the bemfa topic')
    parser.add_argument('--mac', type=str, required=True, help='the mac address of your network card to wake up')
    parser.add_argument('--broadcast', type=str, required=True, help='the broadcast ip of your network')
    parser.add_argument('--host', type=str, required=True, help='the host of your computer you want to suspend')
    parser.add_argument('--key', type=str, required=True, help='ssh-key for the host')

    args = parser.parse_args()

    api = bemfaTcpAPI('bemfa.com', 8344, args.api_key, args.topic)

    # config logging
    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)

    asyncio.run(start_server(api, mac_address=args.mac, broadcast_ip=args.broadcast, host=args.host, key_file=args.key))


if __name__ == '__main__':
    main()
