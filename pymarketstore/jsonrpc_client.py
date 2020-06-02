from __future__ import absolute_import
import numpy as np
import pandas as pd
import re
import requests
import logging
import six
from .jsonrpc import MsgpackRpcClient
from .results import QueryReply
from .stream import StreamConn

logger = logging.getLogger(__name__)


def isiterable(something):
    return isinstance(something, (list, tuple, set))


def get_timestamp(value):
    if value is None:
        return None
    if isinstance(value, (int, np.integer)):
        return pd.Timestamp(value, unit='s')
    return pd.Timestamp(value)


class JsonRpcClient(object):

    def __init__(self, endpoint='http://localhost:5993/rpc', ):
        self.endpoint = endpoint
        self.rpc = MsgpackRpcClient(self.endpoint)

    def _request(self, method, **query):
        try:
            return self.rpc.call(method, **query)
        except requests.exceptions.HTTPError as exc:
            logger.exception(exc)
            raise

    def query(self, params):
        if not isiterable(params):
            params = [params]
        query = self.build_query(params)
        reply = self._request('DataService.Query', **query)
        return QueryReply.from_response(reply)

    def write(self, recarray, tbk, isvariablelength=False):
        data = {}
        data['types'] = [
            recarray.dtype[name].str.replace('<', '')
            for name in recarray.dtype.names
        ]
        data['names'] = recarray.dtype.names
        data['data'] = [
            bytes(buffer(recarray[name])) if six.PY2
            else bytes(memoryview(recarray[name]))
            for name in recarray.dtype.names
        ]
        data['length'] = len(recarray)
        data['startindex'] = {tbk: 0}
        data['lengths'] = {tbk: len(recarray)}
        write_request = {}
        write_request['dataset'] = data
        write_request['is_variable_length'] = isvariablelength
        writer = {}
        writer['requests'] = [write_request]

        try:
            return self.rpc.call("DataService.Write", **writer)
        except requests.exceptions.ConnectionError:
            raise requests.exceptions.ConnectionError(
                "Could not contact server")


    def build_query(self, params):
        reqs = []
        if not isiterable(params):
            params = [params]
        for param in params:
            req = {
                'destination': param.tbk,
            }
            if param.key_category is not None:
                req['key_category'] = param.key_category
            if param.start is not None:
                req['epoch_start'], start_nanosec = divmod(param.start.value, 10**9)

                # support nanosec
                if start_nanosec != 0:
                    req['epoch_start_nanos'] = start_nanosec

            if param.end is not None:
                req['epoch_end'], end_nanosec = divmod(param.end.value, 10 ** 9)

                # support nanosec
                if end_nanosec != 0:
                    req['epoch_end_nanos'] = end_nanosec

            if param.limit is not None:
                req['limit_record_count'] = int(param.limit)
            if param.limit_from_start is not None:
                req['limit_from_start'] = bool(param.limit_from_start)
            if param.functions is not None:
                req['functions'] = param.functions
            reqs.append(req)
        return {
            'requests': reqs,
        }

    def list_symbols(self):
        reply = self._request('DataService.ListSymbols')
        if 'Results' in reply.keys():
            return reply['Results']
        return []

    def destroy(self, tbk):
        """
        Delete a bucket
        :param tbk: Time Bucket Key Name (i.e. "TEST/1Min/Tick" )
        :return: reply object
        """
        destroy_req = {'requests': [{'key': tbk}]}
        reply = self._request('DataService.Destroy', **destroy_req)
        return reply

    def server_version(self):
        resp = requests.head(self.endpoint)
        return resp.headers.get('Marketstore-Version')

    def stream(self):
        endpoint = re.sub('^http', 'ws',
                          re.sub(r'/rpc$', '/ws', self.endpoint))
        return StreamConn(endpoint)

    def __repr__(self):
        return 'MsgPackRPCClient("{}")'.format(self.endpoint)
