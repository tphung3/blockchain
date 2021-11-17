#!/usr/bin/env python3

import re
import sys
import os
import time
import socket
import select
import threading
import NetworkFunctions
import HashTable


def send_catalog_updates(name, port):
    # send update every minute
    while True:
        start = time.time()
        NetworkFunctions.send_catalog_update(name, port)
        time.sleep(60 - (time.time() - start))


class HashTableServer:
    def __init__(self, name):
        self.name = name
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        HashTable.restart()

    @staticmethod
    def send_error(conn, code, msg):
        NetworkFunctions.send_json(conn, {
            "status": "error",
            "error_code": code,
            "error_msg": msg
        })

    def run(self):
        self.socket.bind(('', 0))
        _, self.port = self.socket.getsockname()

        self.socket.listen(8)
        print("Listening on port", self.port)

        # send catalog updates in background
        threading.Thread(target=send_catalog_updates, args=(self.name, self.port), daemon=True).start()

        sockets = set()

        while True:
            inputs = [self.socket] + list(sockets)
            readable, _, _ = select.select(inputs, [], [])

            for s in readable:
                if s == self.socket:
                    # main socket -> accept new connection
                    conn, _ = self.socket.accept()
                    sockets.add(conn)
                    print("Accepted a connection")
                else:
                    # other socket -> handle request
                    try:
                        req = NetworkFunctions.rec_json(s)

                        if req is None:
                            print("Client closed the connection")
                            s.close()
                            sockets.remove(s)
                            continue

                        self.handle_request(s, req)

                    except ValueError:
                        # good request, but invalid JSON -> send error msg and return
                        self.send_error(s, -1, "Request was not in JSON format")

    def handle_request(self, conn, req):
        method = req.get("method", None)
        if method is None:
            self.send_error(conn, -1, "Missing required 'method' property in request")
            return

        if method == "insert":
            key = req.get("key", None)
            if key is None:
                self.send_error(conn, -1, "Missing required 'key' property in request")
                return

            value = req.get("value", None)
            if value is None:
                self.send_error(conn, -1, "Missing required 'value' property in request")
                return

            try:
                HashTable.insert(key, value)
            except TypeError as e:
                self.send_error(conn, 0, str(e))
                return

            NetworkFunctions.send_json(conn, {
                "status": "success"
            })

        elif method == "lookup":
            key = req.get("key", None)
            if key is None:
                self.send_error(conn, -1, "Missing required 'key' property in request")
                return

            try:
                value = HashTable.lookup(key)
            except TypeError as e:
                self.send_error(conn, 0, str(e))
                return

            NetworkFunctions.send_json(conn, {
                "status": "success",
                "result": value 
            })

        elif method == "remove":
            key = req.get("key", None)
            if key is None:
                self.send_error(conn, -1, "Missing required 'key' property in request")
                return

            try:
                value = HashTable.remove(key)
            except TypeError as e:
                self.send_error(conn, 0, str(e))
                return

            NetworkFunctions.send_json(conn, {
                "status": "success",
                "result": value 
            })

        elif method == "scan":
            regex = req.get("regex", None)
            if regex is None:
                self.send_error(conn, -1, "Missing required 'regex' property in request")
                return
            
            try:
                matches = HashTable.scan(regex)
            except TypeError as e:
                self.send_error(conn, 0, str(e))
                return
            except ValueError as e:
                self.send_error(conn, 1, str(e))
                return

            NetworkFunctions.send_json(conn, {
                "status": "success",
                "result": matches
            })

        else:
            self.send_error(conn, -1, method + " method not recognized")
            return


def usage(status):
    print(f"{sys.argv[0]} NAME")
    sys.exit(status)


def main():
    if len(sys.argv) < 2:
        usage(1)

    name = sys.argv[1]

    server = HashTableServer(name)
    server.run()


if __name__ == "__main__":
    main()

