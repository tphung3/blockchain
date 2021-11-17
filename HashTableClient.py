#!/usr/bin/env python3

import sys
import json
import socket
import http.client
import NetworkFunctions


class MessageTransmissionException(Exception):
    pass


class ExceptionFromServer(Exception):
    pass


class HashTableClient:
    def __init__(self):
        self.socket = None
        self.name = None
        self.address = None

    def connect(self, name):
        verbose = True

        if self.socket is not None:
            # in case of reconnect
            self.socket.close()
            verbose = False

        self.name = name
        self.address = NetworkFunctions.find_addr(name)
        if self.address is None:
            if verbose:
                print("Unable to resolve server name:", name, file=sys.stderr)
            return False

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect(self.address)
        except (TimeoutError, InterruptedError, ConnectionRefusedError):
            if verbose:
                print(name + " is not available", file=sys.stderr)
            return False

        return True

    def restart_connection(self):
        self.cleanup()
        self.connect(self.name)
    
    def cleanup(self):
        if self.socket is not None:
            self.socket.close()

    def request(self, json_obj):
        if not self.send_json(json_obj):
            raise MessageTransmissionException("Unable to send JSON to server")

        resp = self.rec_json()

        if resp is None:
            raise MessageTransmissionException("Unable to receive JSON from server")

        status = resp.get("status", None)
        if status is None:
            raise MessageTransmissionException("Missing 'status' property from server")

        if resp['status'] == 'error':
            error_code = resp.get("error_code", None)
            error_msg  = resp.get("error_msg", None)

            if error_code is None or error_msg is None:
                raise MessageTransmissionException("Missing information about error type from server")

            if error_code < 0:
                raise ExceptionFromServer(error_msg)
            
            if error_code == 0:
                raise TypeError(error_msg)
        
        return resp

    def send_json(self, json_obj):
        return NetworkFunctions.send_json(self.socket, json_obj)

    def rec_json(self):
        return NetworkFunctions.rec_json(self.socket)

    def insert(self, key, value):
        # Inserts the given key and value into the hash table.
        self.request({
            "method": "insert",
            "key": key,
            "value": value
        })

    def lookup(self, key):
        # Returns the value associated with a given key.
        resp = self.request({
            "method": "lookup",
            "key": key
        })

        if 'result' not in resp:
            raise MessageTransmissionException("Missing 'result' property from server")

        return resp['result'] 

    def remove(self, key):
        # Removes the key and corresponding value from the hash table, and returns it to the caller.
        resp = self.request({
            "method": "remove",
            "key": key
        })

        if 'result' not in resp:
            raise MessageTransmissionException("Missing 'result' property from server")

        return resp['result'] 

    def scan(self, regex):
        # Returns a list of (key,value) pairs where the key matches the regular expression.
        resp = self.request({
            "method": "scan",
            "regex": regex
        })

        if resp['status'] == "error" and resp['error_code'] == 1:
            raise ValueError(resp['error_msg'])

        if 'result' not in resp:
            raise MessageTransmissionException("Missing 'result' property from server")

        return resp['result'] 

