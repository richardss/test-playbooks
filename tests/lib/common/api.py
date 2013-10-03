import json
import urllib2
import types
import requests

def json_func(self):
    '''monkey-patch a json helpder method for use in urllib2 response object'''
    try:
        return json.loads(self.text)
    except:
        return self.text

class Connection(object):

    def __init__(self, server, verify=False):
        self.server = server
        self.verify = verify

    def login(username=None, password=None):

        # Setup urllib2 for basic password authentication.
        password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, self.server, username, password)
        handler = urllib2.HTTPBasicAuthHandler(password_mgr)
        opener = urllib2.build_opener(handler)
        urllib2.install_opener(opener)

        try:
            self.get('/api')
        except Exception, e:
            raise BaseException(str(e))

    def _request(self, endpoint, data=None, method='GET'):
        method = method.lower()
        headers = dict()
        payload = dict()

        # Locate correct requests method
        if not hasattr(requests, method):
            raise Exception("Unknown request method: %s" % method)
        request_handler = getattr(requests, method)

        # Build url, headers and params
        url = "%s%s" % (self.server, endpoint)
        headers = {'content-type': 'application/json'}
        if data is not None:
            payload = json.dumps(data)

        try:
            response = request_handler(url,
                verify=self.verify,
                headers=headers,
                data=payload)
        except Exception, e:
            err_str = "%s, url: %s" % (str(e), url,)

            if hasattr(e, 'read'):
                err_str += ", %s" % (e.read())
            raise BaseException(err_str)

        # Add convenience attribute 'code' to mimick urllib2 response
        response.code = response.status_code

        return response

    def _request_old(self, endpoint, data=None, method='GET'):
        url = "%s%s" % (self.server, endpoint)
        request = urllib2.Request(url)

        #if method in ['PUT', 'PATCH', 'POST', 'DELETE', 'HEAD', 'OPTIONS']:
        if method != 'GET':
            request.add_header('Content-type', 'application/json')
            request.get_method = lambda: method

        if data is not None:
            request.add_data(json.dumps(data))

        try:
            response = urllib2.urlopen(request)
        except Exception, e:
            err_str = "%s, url: %s" % (str(e), url,)

            if hasattr(e, 'read'):
                err_str += ", %s" % (e.read())
            raise BaseException(err_str)

        # Add convenience .json() method to response object
        response.text = response.read()
        response.json = types.MethodType(json_func, response)
        return response

    def get(self, endpoint):
        return self._request(endpoint)

    def head(self, endpoint):
        return self._request(endpoint, method='HEAD')

    def options(self, endpoint):
        return self._request(endpoint, method='OPTIONS')

    def post(self, endpoint, data):
        return self._request(endpoint, data, method='POST')

    def put(self, endpoint, data):
        return self._request(endpoint, data, method='PUT')

    def patch(self, endpoint, data):
        return self._request(endpoint, data, method='PATCH')

    def delete(self, endpoint):
        return self._request(endpoint, method='DELETE')
