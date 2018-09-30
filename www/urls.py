# -*- coding: utf-8 -*-

'''
https://www.liaoxuefeng.com/wiki/001374738125095c955c1e6d8bb493182103fac9270762a000/00140240726395479019cb0be724e7db42936babd5f9717000
'''

import logging, os, re, time, base64, hashlib

from transwarp.web import get, view, post, ctx, interceptor
from apis import api, APIError, APIValueError, APIPermissionError, APIResourceNotFoundError
from models import User, Blog, Comment
from config import configs

_COOKIE_NAME = 'awesession'
_COOKIE_KEY = configs.session.secret

'''
@view('test_users.html')
@get('/')
def test_users():
    users = User.find_all()
    return dict(users=users)
'''
_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_MD5 = re.compile(r'^[0-9a-f]{32}$')

@api
@post('/api/users')
def register_user():
    print 'register_user'
    i = ctx.request.input(name='', email='', password='')
    name = i.name.strip()
    email = i.email.strip().lower()
    password = i.password
    print name, email, password
    if not name:
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email):
        print 'email match fail'
        raise APIValueError('email')
    if not password or not _RE_MD5.match(password):
        raise APIValueError('password')
    user = User.find_first('where email=?', email)
    if user:
        raise  APIError('register:failed', 'email', 'Email is already in use.')
    user = User(name=name, email=email, password=password, image='http://www.gravatar.com/avatar/%s?d=mm&s=120' %hashlib.md5(email).hexdigest())
    user.insert()
    return user

@view('register.html')
@get('/register')
def register():
    return dict()

def make_signed_cookie(id, password, max_age):
    #build cookie string by: id-expires-md5
    expires = str(int(time.time() + (max_age or 86400)))
    L = [id, expires, hashlib.md5('%s-%s-%s-%s' % (id, password, expires, _COOKIE_KEY)).hexdigest()]
    return '-'.join(L)

def parse_signed_cookie(cookie_str):
    try:
        L = cookie_str.split('-')
        if len(L) != 3:
            return None
        id, expires, md5 = L
        if int(expires) < time.time():
            return None
        user = User.get(id)
        if user is None:
            return None
        if md5 != hashlib.md5('%s-%s-%s-%s' % (id, user.password, expires, _COOKIE_KEY)).hexdigest():
            return None
        return user
    except:
        return None

def check_admin():
    user = ctx.request.user
    if user and user.admin:
        return
    raise APIPermissionError('No permission.')

@interceptor('/')
def user_interceptor(next):
    logging.info('try to bind user from session')
    user = None
    cookie = ctx.request.cookies.get(_COOKIE_NAME)
    if cookie:
        logging.info('parse session cookie...')
        user = parse_signed_cookie(cookie)
        if user:
            logging.info('bind user <%s> to session...' % user.email)
    ctx.request.user = user
    return next()

@view('blogs.html')
@get('/')
def index():
    blogs = Blog.find_all()
    user = User.find_first('where email=?', 'admin@example.com')
    return dict(blogs=blogs, user=user)

@api
@get('/api/users')
def api_get_users():
    users = User.find_by('order by created_at desc')
    for u in users:
        u.password = '******'
    return dict(users=users)
