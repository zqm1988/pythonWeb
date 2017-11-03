# -*- coding: utf-8 -*-
'''
1.url route:map url to function
2.url intercept:intercept url and check authorization
3.view :use to generate HTTP page
4.data model:use to abstract data
5.transaction model:capsulation of request data and response data
'''

import types, os, re, cgi, sys, time, datetime, functools, mimetypes, threading, logging, traceback, urllib

from db import Dict

# import utils

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

ctx = theading.local()

# re_expression of response headers, use to check resposne?
_RE_RESPONSE_STATUS = re.compile(r'^\d\d\d(\ [\w\ ]+)?$')
# macro for header powered_by
_HEADER_X_POWERED_BY = ('X-Powered_By', 'transwarp/1.0')

# use to transfer timezone
_TIMEDELTA_ZERO = datetime.timedelta(0)
_RE_TZ = re.compile('^([\+\-])([0-9]{1,2})\:([0-9]{1,2})$')

# response status
_RESPONSE_STATUSES = {
    # informational
    100: 'Continue',
    101: 'Switching Protocols',
    102: 'Processing',

    # successful
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'On Content',
    205: 'Reset Content',
    206: 'Partial Content',
    207: 'Multi Status',
    226: 'IM Used',

    # redirection
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    307: 'Temporary Redirect',

    # client error
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Failed',
    413: 'Request Entity Too Large',
    414: 'Request URI Too Long',
    415: 'Unsupported Media Type',
    416: 'Requested Range Not Satisfiable',
    417: 'Expectation Failed',
    418: 'I\'m a teapoot',
    422: 'Unproecssable Entity',
    423: 'Locked',
    424: 'Failed Dependency',
    426: 'Upgrade Required',

    # server error
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
    505: 'HTTP Version Not Supported',
    507: 'Insufficient Storage',
    510: 'Not Extended',
}

_RESPONSE_HEADERS = (
    'Accept-Ranges',
    'Age',
    'Allow',
    'Cache-Control',
    'Connection',
    'Content-Encoding',
    'Content-Language',
    'Content-Length',
    'Content-Location',
    'Content-MD5',
    'Content-Disposition',
    'Content-Range',
    'Content-Type',
    'Date',
    'ETag',
    'Expires',
    'Last-Modified',
    'Link',
    'Location',
    'P3P',
    'Pragma',
    'Proxy-Authenticate',
    'Refresh',
    'Retry-After',
    'Server',
    'Set-Cookie',
    'Strict-Transport-Security',
    'Trailer',
    'Transfer-Encoding',
    'Vary',
    'Via',
    'Warning',
    'WWW-Authenticate',
    'X-Frame-Options',
    'X-XSS-Protection',
    'X-Content-Type-Options',
    'X-Forwarded-Proto',
    'X-Powered-By',
    'X-UA-Compatible',
)


class UTC(datetime.tzinfo):
    def __init__(self, utc):
        utc = str(utc.strip().upper())
        mt = _RE_TZ.match(utc)
        if mt:
            minus = mt.group(1) == '-'
            h = int(mt.group(2))
            m = int(mt.group(3))
            if minus:
                h, m = (-h), (-m)
            self._utcoffset = datetime.timedelta(hours=h, minutes=m)
            self._tzname = 'UTC%s' % utc
        else:
            raise ValueError('bad utc time zone')

    def utcoffset(self, dt):
		'''
        offset with standard timezone
        '''
        return self._utcoffset

    def dst(self, dt):
        '''
        daylight saving time
        '''
        return _TIMEDELTA_ZERO

    def tzname(self, dt):
        '''
        name of the timezone
        '''
        return self._tzname

    def __str__(self):
        return 'UTC timezone info object (%s)' % self._tzname

    __repr__ = __str__


UTC_0 = UTC('+00:00')


class _HttpError(Exception):
    '''
    Httperror that defines http error code
    '''

    def __init__(self, code):
        super(_HttpError, self).__init__()
        self.status = '%d %s' % (code, _RESPONSE_STATUSES[code])
        self._headers = None

    def header(self, name, value):
        if not self._headers:
            self._headers = [_HEADER_X_POWERED_BY]
        self._headers.append((name, value))

    @property
    def headers(self):
        if hasattr(self, '_headers'):
            return self._headers
        return []

    def __str__(self):
        return self.status

    __repr__ = __str__


class _RedirectError(_HttpError):
	"""
	RedirectError that defines http redirect code.
	"""
	def __init__(self, code, location):
		# type: (object, object) -> object
		super(_RedirectError, self).__init__(code)
		self.location = location

	def __str__(self):
		return '%s, %s' % (self.status, self.location)

	__repr__ = __str__

class HttpError(Exception):
	"""
	HTTP Exceptions
	"""
    @staticmethod
	def badrequest():
		return _HttpError(400)

	@staticmethod
	def unauthorized():
		return _HttpError(401)

	@staticmethod
	def forbidden():
		return _HttpError(403)

    @staticmethod
    def notfound():
        return _HttpError(404)

    @staticmethod
    def conflict():
        return _HttpError(409)

    @staticmethod
    def internalerror():
        return _HttpError(500)

    @staticmethod
    def redirect(location):
        return _RedirectError(301, location)

    @staticmethod
    def found(location):
        return _RedirectError(302, location)

    @staticmethod
    def seeother(location):
        return _RedirectError(303, location)

_RESPONSE_HEADER_DICT = dict(zip(map(lambda x: x.upper(), _RESPONSE_HEADERS), _RESPONSE_HEADERS))


class Request(object):
    """
    request object, use to get http request info
    """
    def __init__(self, environ):
        self._environ = environ

    def _parse_input(self):
    """
    pase parmeter from wsgi into a dict object
    """
        def _convert(item):
            if isinstance(item, list):
                return [utils.to_unicode(i.value) for i in item]
            if item.filename:
                    return MultipartFile(item)
            return utils.to_unicode(item.value)
        fs = cgi.FieldStorage(fp=self._environ['wsgi.input'], environ=self._environ, keep_blank_values=True)
        inputs = dict()
        for key in fs:
            inputs[key] = _convert(fs[key])
        return inputs

    def _get_raw_input(self):
        if not hasattr(self, '_raw_input'):
            self._raw_input = self._parse_input()
        return self._raw_input

    def __getitem__(self, key):
        r = self._get._raw_input()[key]
        if isinstance(r, list):
            return r[0]
        return r

    # get value from key
    def get(self, key, default=None):
        r = self._get_raw_input().get(key, default)
        if isinstance(r, list):
            return r[0]
        return r

    def gets(self, key):
        r = self._get_raw_input()[key]
        if isinstance(r, list):
            return r[:]
        return [r]

    # return dict
    def input(self):
        copy = Dict(**kw)
        raw = self._get_raw_input()
        for k,v in raw.iteritems():
            copy[k] = v[0] if isinstance(v, list) else v
        return  copy

    def get_body(self):
        fp = self._environ['wsgi.input']
        return fp.read()

    @property
    def remote_addr(self):
        return self._environ.get('REMOTE_ADDR', '0.0.0.0')

    @property
    def document_root(self):
        return self._environ.get('DOCUMENT_ROOT', '')

    @property
    def query_string(self):
        return self._environ.get('QUERY_STRINg', '')

    @property
    def environ(self):
        return self._environ

    @property
    def request_method(self):
        return self._environ['REQUEST_METHOD']

    # return path of URL
    @property
    def path_info(self):
        return urllib.unquote(self._environ.get('PATH_INFO', ''))

    @property
    def host(self):
        return self._environ.get('HTTP_HOST', '')

    def _get_headers(self):
        if not hasattr(self, '_headers'):
            hdrs = {}
            for k, v in self._environ.iteritems():
                if k.startswith('HTTP_'):
                    hdrs[k[5:].replace('_', '-').upper()] = v.decode('utf-8')
            self._headers = hdrs
        return self._headers

    # return  Headers of HTTP
    @property
    def headers(self):
        return dict(**self._get_headers())

    @property
    def header(self, header, default=None):
        return self._get_headers().get(header.upper(), default)

    def _get_cookies(self):
        if not hasattr(self, '_cookies'):
            cookies = {}
            cookie_str = self._environ.get('HTTP_COOKIE')
            if cookie_str:
                for c in cookie_str.split(';'):
                    pos = c.find('=')
                    if pos > 0:
                        cookies[c[:pos].strip()] = urllib.unquote(c[pos+1:])
            self._cookies = cookie
        return self._cookies

    # return Cookie value
    @proerty
    def cookie(self):
        return Dict(**self._get_cookies())

    def cookie(self, name, default=None):
        return self._get_cookies().get(name, default)


class Response(object):
    # set header
    def set_header(self, key, value):
        pass

    # set cookie
    def set_cookie(self, name, value, max_age=None, expires=None, path='/'):
        pass

    # set status 404?
    @property
    def status(self):
        pass

    @status.setter
    def status(self, value):
        pass


def get(path):
    pass


def post(path):
    pass


def view(path):
    pass


def interceptor(pattern):
    pass


class TemplateEngine(object):
    def __call__(self, path, model):
        pass


class Jinja2TemplateEngine(TemplateEngine):
    def __init__(self, templ_dir, **kw):
        from jinja2 import Environment, FileSystemLoader
        self.env = Environment(loader=FileSystemLoader(templ_dir), **kw)

    def __call__(self, path, model):
        return self._env.get_template(path).render(**model).encode('utf-8')
