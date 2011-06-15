#!/usr/bin/python
# Copyright 2011 Zuse Institute Berlin
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import httplib, urlparse, socket, base64
import os
try: import simplejson as json
except ImportError: import json

if 'SCALARIS_JSON_URL' in os.environ:
    default_url = os.environ['SCALARIS_JSON_URL']
else:
    default_url = 'http://localhost:8000'
"""default URL and port to a scalaris node"""
default_timeout = 5
"""socket timeout in seconds"""
default_path = '/jsonrpc.yaws'
"""path to the json rpc page"""

class JSONConnection(object):
    """
    Abstracts connections to Scalaris using JSON
    """
    
    def __init__(self, url = default_url, timeout = default_timeout):
        """
        Creates a JSON connection to the given URL using the given TCP timeout
        """
        try:
            uri = urlparse.urlparse(url)
            self._conn = httplib.HTTPConnection(uri.hostname, uri.port,
                                                timeout = timeout)
        except Exception as instance:
            raise ConnectionException(instance)

    def call(self, function, params):
        """
        Calls the given function with the given parameters via the JSON
        interface of Scalaris.
        """
        params = {'jsonrpc': '2.0',
                  'method': function,
                  'params': params,
                  'id': 0}
        try:
            # use compact JSON encoding:
            params_json = json.dumps(params, separators=(',',':'))
            headers = {"Content-type": "application/json; charset=utf-8"}
            # no need to quote - we already encode to json:
            #self._conn.request("POST", default_path, urllib.quote(params_json), headers)
            self._conn.request("POST", default_path, params_json, headers)
            response = self._conn.getresponse()
            #print response.status, response.reason
            if (response.status < 200 or response.status >= 300):
                raise ConnectionException(response)
            data = response.read().decode('utf-8')
            response_json = json.loads(data)
            return response_json['result']
        except Exception as instance:
            raise ConnectionException(instance)

    @staticmethod
    def encode_value(value):
        """
        Encodes the value to the form required by the Scalaris JSON API
        """
        if isinstance(value, bytearray):
            return {'type': 'as_bin', 'value': (base64.b64encode(value)).decode('ascii')}
        else:
            return {'type': 'as_is', 'value': value}

    @staticmethod
    def decode_value(value):
        """
        Decodes the value from the Scalaris JSON API form to a native type
        """
        if ('type' not in value) or ('value' not in value):
            raise UnknownException(value)
        if value['type'] == 'as_bin':
            return bytearray(base64.b64decode(value['value'].encode('ascii')))
        else:
            return value['value']
    
    # result: {'status': 'ok', 'value': xxx} or
    #         {'status': 'fail', 'reason': 'timeout' or 'not_found'}
    @staticmethod
    def process_result_read(result):
        """
        Processes the result of a read operation.
        Returns the read value on success.
        Raises the appropriate exception if the operation failed.
        """
        if isinstance(result, dict) and 'status' in result and len(result) == 2:
            if result['status'] == 'ok' and 'value' in result:
                return JSONConnection.decode_value(result['value'])
            elif result['status'] == 'fail' and 'reason' in result:
                if result['reason'] == 'timeout':
                    raise TimeoutException(result)
                elif result['reason'] == 'not_found':
                    raise NotFoundException(result)
        raise UnknownException(result)
        
    # result: {'status': 'ok'} or
    #         {'status': 'fail', 'reason': 'timeout'}
    @staticmethod
    def process_result_write(result):
        """
        Processes the result of a write operation.
        Raises the appropriate exception if the operation failed.
        """
        if isinstance(result, dict):
            if result == {'status': 'ok'}:
                return None
            elif result == {'status': 'fail', 'reason': 'timeout'}:
                raise TimeoutException(result)
        raise UnknownException(result)
        
    # result: {'status': 'ok'} or
    #         {'status': 'fail', 'reason': 'timeout' or 'abort'}
    @staticmethod
    def process_result_commit(result):
        """
        Processes the result of a commit operation.
        Raises the appropriate exception if the operation failed.
        """
        if isinstance(result, dict) and 'status' in result:
            if result == {'status': 'ok'}:
                return None
            elif result['status'] == 'fail' and 'reason' in result and len(result) == 2:
                if result['reason'] == 'timeout':
                    raise TimeoutException(result)
                elif result['reason'] == 'abort':
                    raise AbortException(result)
        raise UnknownException(result)
        
    # results: {'status': 'ok'} or
    #          {'status': 'fail', 'reason': 'timeout' or 'abort' or 'not_found'} or
    #          {'status': 'fail', 'reason': 'key_changed', 'value': xxx}
    @staticmethod
    def process_result_testAndSet(result):
        """
        Processes the result of a testAndSet operation.
        Raises the appropriate exception if the operation failed.
        """
        if isinstance(result, dict) and 'status' in result:
            if result == {'status': 'ok'}:
                return None
            elif result['status'] == 'fail' and 'reason' in result:
                if len(result) == 2:
                    if result['reason'] == 'timeout':
                        raise TimeoutException(result)
                    elif result['reason'] == 'abort':
                        raise AbortException(result)
                    elif result['reason'] == 'not_found':
                        raise NotFoundException(result)
                elif result['reason'] == 'key_changed' and 'value' in result and len(result) == 3:
                    raise KeyChangedException(result, JSONConnection.decode_value(result['value']))
        raise UnknownException(result)
    
    # results: {'status': 'ok'}
    @staticmethod
    def process_result_publish(result):
        """
        Processes the result of a publish operation.
        Raises the appropriate exception if the operation failed.
        """
        if result == {'status': 'ok'}:
            return None
        raise UnknownException(result)
    
    # results: {'status': 'ok'} or
    #          {'status': 'fail', 'reason': 'timeout' or 'abort'}
    @staticmethod
    def process_result_subscribe(result):
        """
        Processes the result of a subscribe operation.
        Raises the appropriate exception if the operation failed.
        """
        JSONConnection.process_result_commit(result)
    
    # results: {'status': 'ok'} or
    #          {'status': 'fail', 'reason': 'timeout' or 'abort' or 'not_found'}
    @staticmethod
    def process_result_unsubscribe(result):
        """
        Processes the result of a unsubscribe operation.
        Raises the appropriate exception if the operation failed.
        """
        if result == {'status': 'ok'}:
            return None
        elif isinstance(result, dict) and 'status' in result:
            if result['status'] == 'fail' and 'reason' in result and len(result) == 2:
                if result['reason'] == 'timeout':
                    raise TimeoutException(result)
                elif result['reason'] == 'abort':
                    raise AbortException(result)
                elif result['reason'] == 'not_found':
                    raise NotFoundException(result)
        raise UnknownException(result)
    
    # results: [urls=str()]
    @staticmethod
    def process_result_getSubscribers(result):
        """
        Processes the result of a getSubscribers operation.
        Returns the list of subscribers on success.
        Raises the appropriate exception if the operation failed.
        """
        if isinstance(result, list):
            return result
        raise UnknownException(result)

    # results: {'ok': xxx, 'results': ['ok' or 'locks_set' or 'undef']} or
    #          {'failure': 'timeout', 'ok': xxx, 'results': ['ok' or 'locks_set' or 'undef']}
    @staticmethod
    def process_result_delete(result):
        """
        Processes the result of a delete operation.
        Returns the tuple
        (<success (True | 'timeout')>, <number of deleted items>, <detailed results>) on success.
        Raises the appropriate exception if the operation failed.
        """
        if isinstance(result, dict) and 'ok' in result and 'results' in result:
            if 'failure' not in result:
                return (True, result['ok'], result['results'])
            elif result['failure'] == 'timeout':
                return ('timeout', result['ok'], result['results'])
        raise UnknownException(result)
    
    # results: ['ok' or 'locks_set' or 'undef']
    @staticmethod
    def create_delete_result(result):
        """
        Creates a new DeleteResult from the given result list.
        """
        ok = 0
        locks_set = 0
        undefined = 0
        if isinstance(result, list):
            for element in result:
                if element == 'ok':
                    ok += 1
                elif element == 'locks_set':
                    locks_set += 1
                elif element == 'undef':
                    undefined += 1
                else:
                    raise UnknownException('Unknown reason ' + element + 'in ' + result)
            return DeleteResult(ok, locks_set, undefined)
        raise UnknownException('Unknown result ' + result)

    # results: {'tlog': xxx,
    #           'results': [{'status': 'ok'} or {'status': 'ok', 'value': xxx} or
    #                       {'status': 'fail', 'reason': 'timeout' or 'abort' or 'not_found'}]}
    @staticmethod
    def process_result_req_list(result):
        """
        Processes the result of a req_list operation.
        Returns the tuple (<tlog>, <result>) on success.
        Raises the appropriate exception if the operation failed.
        """
        if 'tlog' not in result or 'results' not in result or \
            not isinstance(result['results'], list) or len(result['results']) < 1:
            raise UnknownException(result)
        return (result['tlog'], result['results'])
    
    # result: 'ok'
    @staticmethod
    def process_result_nop(result):
        """
        Processes the result of a nop operation.
        Raises the appropriate exception if the operation failed.
        """
        if result != 'ok':
            raise UnknownException(result)
    
    @staticmethod
    def newReqList():
        """
        Returns a new ReqList object allowing multiple parallel requests.
        """
        return _JSONReqList()
    
    def close(self):
        self._conn.close()

class AbortException(Exception):
    """
    Exception that is thrown if a the commit of a write operation on a Scalaris
    ring fails.
    """
    
    def __init__(self, raw_result):
        self.raw_result = raw_result
    def __str__(self):
        return repr(self.raw_result)

class ConnectionException(Exception):
    """
    Exception that is thrown if an operation on a Scalaris ring fails because
    a connection does not exist or has been disconnected.
    """
    
    def __init__(self, raw_result):
        self.raw_result = raw_result
    def __str__(self):
        return repr(self.raw_result)

class KeyChangedException(Exception):
    """
    Exception that is thrown if a test_and_set operation on a Scalaris ring
    fails because the old value did not match the expected value.
    """
    
    def __init__(self, raw_result, old_value):
        self.raw_result = raw_result
        self.old_value = old_value
    def __str__(self):
        return repr(self.raw_result) + ', old value: ' + repr(self.old_value)

class NodeNotFoundException(Exception):
    """
    Exception that is thrown if a delete operation on a Scalaris ring fails
    because no Scalaris node was found.
    """
    
    def __init__(self, raw_result):
        self.raw_result = raw_result
    def __str__(self):
        return repr(self.raw_result)

class NotFoundException(Exception):
    """
    Exception that is thrown if a read operation on a Scalaris ring fails
    because the key did not exist before.
    """
    
    def __init__(self, raw_result):
        self.raw_result = raw_result
    def __str__(self):
        return repr(self.raw_result)

class TimeoutException(Exception):
    """
    Exception that is thrown if a read or write operation on a Scalaris ring
    fails due to a timeout.
    """
    
    def __init__(self, raw_result):
        self.raw_result = raw_result
    def __str__(self):
        return repr(self.raw_result)

class UnknownException(Exception):
    """
    Generic exception that is thrown during operations on a Scalaris ring, e.g.
    if an unknown result has been returned.
    """
    
    def __init__(self, raw_result):
        self.raw_result = raw_result
    def __str__(self):
        return repr(self.raw_result)

class DeleteResult(object):
    """
    Stores the result of a delete operation.
    """
    def __init__(self, ok, locks_set, undefined):
      self.ok = ok
      self.locks_set = locks_set
      self.undefined = undefined

class TransactionSingleOp(object):
    """
    Single write or read operations on Scalaris.
    """
    
    def __init__(self, conn = JSONConnection()):
        """
        Create a new object using the given connection
        """
        self._conn = conn

    def read(self, key):
        """
        Read the value at key
        """
        result = self._conn.call('read', [key])
        return self._conn.process_result_read(result)

    def write(self, key, value):
        """
        Write the value to key
        """
        value = self._conn.encode_value(value)
        result = self._conn.call('write', [key, value])
        self._conn.process_result_commit(result)
    
    def testAndSet(self, key, oldvalue, newvalue):
        """
        Atomic test and set, i.e. if the old value at key is oldvalue, then
        write newvalue.
        """
        oldvalue = self._conn.encode_value(oldvalue)
        newvalue = self._conn.encode_value(newvalue)
        result = self._conn.call('test_and_set', [key, oldvalue, newvalue])
        self._conn.process_result_testAndSet(result)

    def nop(self, value):
        """
        No operation (may be used for measuring the JSON overhead).
        """
        value = self._conn.encode_value(value)
        result = self._conn.call('nop', [value])
        self._conn.process_result_nop(result)
    
    def closeConnection(self):
        """
        Close the connection to Scalaris
        (it will automatically be re-opened on the next request).
        """
        self._conn.close()

class Transaction(object):
    """
    Write or read operations on Scalaris inside a transaction.
    """
    
    def __init__(self, conn = JSONConnection()):
        """
        Create a new object using the given connection
        """
        self._conn = conn
        self._tlog = None
    
    def newReqList(self):
        """
        Returns a new ReqList object allowing multiple parallel requests.
        """
        return self._conn.newReqList()
    
    
    def req_list(self, reqlist):
        """
        Issues multiple parallel requests to Scalaris.
        Request lists can be created using newReqList().
        The returned list has the following form:
        [{'status': 'ok'} or {'status': 'ok', 'value': xxx} or
        {'status': 'fail', 'reason': 'timeout' or 'abort' or 'not_found'}].
        The elements of this list can be processed with process_result_read(),
        process_result_write() and process_result_commit().
        """
        if self._tlog == None:
            result = self._conn.call('req_list', [reqlist.getRequests()])
        else:
            result = self._conn.call('req_list', [self._tlog, reqlist.getRequests()])
        (tlog, result) = self._conn.process_result_req_list(result)
        self._tlog = tlog
        return result
    
    def process_result_read(self, result):
        """
        Processes a result element from the list returned by req_list() which
        originated from a read operation.
        Returns the read value on success.
        Raises the appropriate exceptions if a failure occurred during the
        operation.
        """
        return self._conn.process_result_read(result)

    def process_result_write(self, result):
        """
        Processes a result element from the list returned by req_list() which
        originated from a write operation.
        Raises the appropriate exceptions if a failure occurred during the
        operation.
        """
        return self._conn.process_result_write(result)

    def process_result_commit(self, result):
        """
        Processes a result element from the list returned by req_list() which
        originated from a commit operation.
        Raises the appropriate exceptions if a failure occurred during the
        operation.
        """
        return self._conn.process_result_commit(result)
    
    def commit(self):
        """
        Issues a commit operation to Scalaris validating the previously
        created operations inside the transaction.
        """
        result = self.req_list(self.newReqList().addCommit())[0]
        self.process_result_commit(result)
        # reset tlog (minor optimization which is not done in req_list):
        self._tlog = None
    
    def abort(self):
        """
        Aborts all previously created operations inside the transaction.
        """
        self._tlog = None
    
    def read(self, key):
        """
        Issues a read operation to Scalaris and adds it to the current
        transaction.
        """
        result = self.req_list(self.newReqList().addRead(key))[0]
        return self.process_result_read(result)
    
    def write(self, key, value):
        """
        Issues a write operation to Scalaris and adds it to the current
        transaction.
        """
        result = self.req_list(self.newReqList().addWrite(key, value))[0]
        self.process_result_commit(result)

    def nop(self, value):
        """
        No operation (may be used for measuring the JSON overhead).
        """
        value = self._conn.encode_value(value)
        result = self._conn.call('nop', [value])
        self._conn.process_result_nop(result)
    
    def closeConnection(self):
        """
        Close the connection to Scalaris
        (it will automatically be re-opened on the next request).
        """
        self._conn.close()

class _JSONReqList(object):
    """
    Request list for use with Transaction.req_list()
    """
    
    def __init__(self):
        """
        Create a new object using a JSON connection.
        """
        self.requests = []
    
    def addRead(self, key):
        """
        Adds a read operation to the request list.
        """
        self.requests.append({'read': key})
        return self
    
    def addWrite(self, key, value):
        """
        Adds a write operation to the request list.
        """
        self.requests.append({'write': {key: JSONConnection.encode_value(value)}})
        return self
    
    def addCommit(self):
        """
        Adds a commit operation to the request list.
        """
        self.requests.append({'commit': ''})
        return self
    
    def getRequests(self):
        """
        Gets the collected requests.
        """
        return self.requests

class PubSub(object):
    """
    Publish and subscribe methods accessing Scalaris' pubsub system
    """
    
    def __init__(self, conn = JSONConnection()):
        """
        Create a new object using the given connection.
        """
        self._conn = conn

    def publish(self, topic, content):
        """
        Publishes content under topic.
        """
        # note: do NOT encode the content, this is not decoded on the erlang side!
        # (only strings are allowed anyway)
        # content = self._conn.encode_value(content)
        result = self._conn.call('publish', [topic, content])
        self._conn.process_result_publish(result)

    def subscribe(self, topic, url):
        """
        Subscribes url for topic.
        """
        # note: do NOT encode the URL, this is not decoded on the erlang side!
        # (only strings are allowed anyway)
        # url = self._conn.encode_value(url)
        result = self._conn.call('subscribe', [topic, url])
        self._conn.process_result_subscribe(result)

    def unsubscribe(self, topic, url):
        """
        Unsubscribes url from topic.
        """
        # note: do NOT encode the URL, this is not decoded on the erlang side!
        # (only strings are allowed anyway)
        # url = self._conn.encode_value(url)
        result = self._conn.call('unsubscribe', [topic, url])
        self._conn.process_result_unsubscribe(result)

    def getSubscribers(self, topic):
        """
        Gets the list of all subscribers to topic.
        """
        result = self._conn.call('get_subscribers', [topic])
        return self._conn.process_result_getSubscribers(result)

    def nop(self, value):
        """
        No operation (may be used for measuring the JSON overhead).
        """
        value = self._conn.encode_value(value)
        result = self._conn.call('nop', [value])
        self._conn.process_result_nop(result)
    
    def closeConnection(self):
        """
        Close the connection to Scalaris
        (it will automatically be re-opened on the next request).
        """
        self._conn.close()

class ReplicatedDHT(object):
    """
    Non-transactional operations on the replicated DHT of Scalaris
    """
    
    def __init__(self, conn = JSONConnection()):
        """
        Create a new object using the given connection.
        """
        self._conn = conn

    # returns the number of successfully deleted items
    # use getLastDeleteResult() to get more details
    def delete(self, key, timeout = 2000):
        """
        Tries to delete the value at the given key.
        
        WARNING: This function can lead to inconsistent data (e.g. deleted items
        can re-appear). Also when re-creating an item the version before the
        delete can re-appear.
        """
        result = self._conn.call('delete', [key, timeout])
        (success, ok, results) = self._conn.process_result_delete(result)
        self._lastDeleteResult = results
        if success == True:
            return ok
        elif success == 'timeout':
            raise TimeoutException(result)
        else:
            raise UnknownException(result)

    def getLastDeleteResult(self):
        """
        Returns the result of the last call to delete().
        
        NOTE: This function traverses the result list returned by Scalaris and
        therefore takes some time to process. It is advised to store the returned
        result object once generated.
        """
        return self._conn.create_delete_result(self._lastDeleteResult)

    def nop(self, value):
        """
        No operation (may be used for measuring the JSON overhead).
        """
        value = self._conn.encode_value(value)
        result = self._conn.call('nop', [value])
        self._conn.process_result_nop(result)
    
    def closeConnection(self):
        """
        Close the connection to Scalaris
        (it will automatically be re-opened on the next request).
        """
        self._conn.close()

def str_to_list(value):
    """
    Converts a string to a list of integers.
    If the expected value of a read operation is a list, the returned value
    could be (mistakenly) a string if it is a list of integers.
    """
    if (isinstance(value, str) or isinstance(value, unicode)):
        chars = list(value)
        return [ord(char) for char in chars]
    else:
        return value
