# -*- coding: utf-8 -*-

"""
1.简单的数据库操作
	一次数据库访问：数据库链接=》游标对象=》执行sql=》处理异常=》清理资源。
	db模块对这些过程进行封装，使用户仅需关注sql语句
2.数据安全
	用户请求以多线程处理时，为了避免多线程下的数据共享引起的数据混乱，
	需要将数据链接以TrheadLocal对象传入。

设计db接口：
	1.设计原则：
		设计简单易用的api接口
	2.接口设计
		1.初始化数据库链接
			create_engine:
				1.为数据库链接准备需要的配置信息
				2.创建数据库链接（由生成的全局对象engine的connect方法提供）
			from transwarp import db
			db.create_engine(user='root',
							password='password',
							database='test',
							host='127.0.0.1',
							port=3306)

		2.执行sql dml
			select:
				1.支持一个数据库链接里执行多个sql语句
				2.支持链接的自动获取和释放
			users = db.select('select * from user')
			# users =>
			# [
			#	{"id":1, "name":"Micheal"},
			# ]

		3.支持事务
			transaction 函数封装了如下功能：
				1.事务嵌套，内层事务会自动合并到外层事务中，这种事务模型足够满足需求
"""

import time
import uuid
import functools
import threading
import logging

#global engine object:
engine = None

def next_id(t=None):
	"""
	generate a unique id, format:"currentTimeRandom"
	"""
	if t is None:
		t = time.time()
	return '%015d%s000' % (int(t*1000), uuid.uuid4().hex)

def _profiling(start, sql=''):
	"""
	record sql execute time
	"""
	t = time.time() - start
	if t > 0.1:
		logging.warning('[PROFILING] [DB] %s:%s' % (t, sql))
	else:
		logging.info('[PORFILING] [DB] %s:%s' % (t, sql))

class Dict(dict):
	"""
	Dictionary object
	a simple dictionary class that can access value by property
	"""
	def __init__(self, names=(), values=(), **kw):
		super(Dict, self).__init__(**kw)
		for k,v in zip(names, values):
			self[k] = v

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r"'Dict' object has no attribute '%s'" % key)

	def __setattr__(sekf, key, value):
		self[key] = value

class DBError(Exception):
	pass

class MultiColumnsError(DBError):
	pass

class _Engine(object):
	"""
	database engine object
	save engine created by create_engine
	"""
	def __init__(self, connect):
		self._connect = connect

	def connect(self):
		return self._connect()

class _LazyConnection(object):
	def __init__(self):
		self.connection = None

	def cursor(self):
		if self.connection is None:
			_connection = engine.connect()
			logging.info('[CONNECTION] [OPEN] connection <%s>...' % hex(id(_connection)))
			self.connection = _connection
		return self.connection.cursor()

	def commit(self):
		self.connection.commit()

	def rollback(self):
		self.connection.rollback()

	def cleanup(self):
		if self.connection:
			_connection = self.connection
			self.connection = None
			logging.info('[CONNECTION] [CLOSE] connection <%s>...' % hex(id(_connection)))
			_connection.close()

class _DbCtx(threading.local):
	"""
	db模块的核心对象，数据库链接的上下文对象，负责从数据库获取和释放资源
	取得的链接是lazyConnection，因此只有调用cursor对象时，才会真正获取数据库链接
	该对象时一个thread local对象，因此绑定在此对象上的数据仅对本线程可见
	"""
	def __init__(self):
		self.connection = None
		self.transactions = 0

	def is_init(self):
		"""
		return a bool value, if the object is initialized
		"""
		return self.connection is not None

	def init(self):
		"""
		initialize context of the connection, get a lazyConnection object
		"""
		logging.info('open lazy connection...')
		self.connection = _LazyConnection()
		self.transactions = 0
	
	def cleanup(self):
		"""
		cleanup connection object, close connection
		"""
		self.connection.cleanup()
		self.connection = None

	def cursor(self):
		"""
		get cursor object
		"""
		return self.connection.cursor()

#thread-local db context:
_db_ctx = _DbCtx()

class _ConnectionCtx(object):
	"""
	"""
	def __enter__(self):
		global _db_ctx
		self.should_cleanup = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_cleanup = True
		return self
	
	def __exit__(self, exctype, excvalue, traceback):
		"""
		release resource
		"""
		global _db_ctx
		if self.should_cleanup:
			_db_ctx.cleanup()

class _TransactionCtx(object):
	def __enter__(self):
		global _db_ctx
		self.should_close_conn = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_close_conn = True
		_db_ctx.transactions += 1
		logging.info('begin transaction...' if _db_ctx.transactions == 1 else 'join current transaction...')
		return self

	def __exit__(self, exctype, excvalue, traceback):
		global _db_ctx
		_db_ctx.transactions -= 1
		try:
			if _db_ctx.transactions == 0:
				if exctype is None:
					self.commit()
				else:
					self.rollback()
		finally:
			if self.should_close_conn:
				_db_ctx.cleanup()

	def commit(self):
		global _db_ctx
		logging.info('commit transaction...')
		try:
			_db_ctx.connection.commit()
			logging.info('commit ok.')
		except:
			logging.warning('commit failed. try rollback...')
			_db_ctx.connection.rollback()
			logging.warning('rollback ok.')
			raise

	def rollback(self):
		global _db_ctx
		logging.warning('rollback tarnsaction...')
		_db_ctx.connection.rollback()
		logging.info('rollback ok.')

def create_engine(user, password, database, host='127.0.0.1', port=3306, **kw):
	"""
	db模型的核心函数，用于链接数据库，生成全局对象engine
	engine对象持有数据库链接
	"""
	import mysql.connector
	global engine
	if engine is not None:
		raise DBError('Engine is already initialized')
	params = dict(user=user, password=password, database=database, host=host, port=port)
	defaults = dict(use_unicode=True, charset='utf8', collation='utf8_general_ci', autocommit=False)
	for k,v in defaults.iteritems():
		params[k] = kw.pop(k, v)
	params.update(kw)
	params['buffered']= True
	engine = _Engine(lambda:mysql.connector.connect(**params))
	#test connection...
	logging.info('Init mysql engine <%s> ok.' % hex(id(engine)))

def connection():
	"""
	db模块核心函数，用于获取一个数据库链接
	通过_ConnectionCtx对_db_ctx封装，使惰性链接可以自动获取和释放，
	也就是可以使用with语法来处理数据库链接
	_ConnectionCtx 实现with语法
	"""
	return _ConnectionCtx()

def with_connection(func):
	"""
	@with_connection
		def foo(*args, **kw):
			f1()
			f2()
			f3()
	"""
	@functools.wraps(func)
	def _wrapper(*args, **kw):
		with _ConnectionCtx():
			return func(*args, **kw)
	return _wrapper

def transaction():
	"""
	支持嵌套
		with db.transaction():
			transaction1
			transaction2
			...
	"""
	return _TransactionCtx()

def with_transaction(func):
	"""
	>>> @with_transaction
	... def update_profile(id, name, rollback):
	...		u = dict(id=id, name=name, email='%s@test.org' % name, passwd=name,last_modified=time.time())
	...		insert('user', **u)
	...		update('update user set passwd=? where id=?', name.upper(), id)
	...		if rollback:
	...			raise StandardError('will cause rollback...')
	
	>>> update_profile(8080, 'Julia', False)

	>>> select_one('select * from user where id=?', 8080).passwd
	u'JULIA'
	
	>>> update_profile(9000, 'Robert', True)
	Traceback (most recent call last):
		...
	StandardError: will cause rollback...
	"""
	@functools.wraps(func)
	def _wrapper(*args, **kw):
		start = time.time()
		with _TransactionCtx():
			func(*args, **kw)
		_profiling(start)
	return _wrapper

@with_connection
def _select(sql, first, *args):
	"""
	执行SQL，返回一个结果 或者多个结果组成的列表
	"""
	global _db_ctx
	cursor = None
	sql = sql.replace('?', '%s')
	logging.info('SQL: %s, ARGS: %s' % (sql, args))
	try:
		cursor = _db_ctx.connection.cursor()
		cursor.execute(sql, args)
		if cursor.description:
			names = [x[0] for x in cursor.description]
		if first:
			values = cursor.fetchone()
			if not values:
				return None
			return Dict(names, values)
		return [Dict(names, x) for x in cursor.fetchall()]
	finally:
		if cursor:
			cursor.close()

def select_one(sql, *args):
	"""
	执行sql，仅返回一个结果
	如果没有结果，返回None

	>>> u1 = dict(id=100, name='Alice', email='alice@test.org', passwd='ABC-12345', last_modified=time.time())
	>>> u2 = dict(id=101, name='Sarah', email='sarah@test.org', passwd='ABC-12345', last_modified=time.time())
	>>> insert('user', **u1)
	1

	>>> insert('user', **u2)
	1

	>>> u = select_one('select * from user where id=?', 100)
	>>> u.name
	u'Alice'

	>>> select_one('select * from user where email=?', 'abc@email.com')
	>>> u2 = select_one('select * from user where passwd=? order by email', 'ABC-12345')
	>>> u2.name
	u'Alice'
	"""
	return _select(sql, True, *args)

def select_int(sql, *args):
	"""
	>>> u1 = dict(id=96900, name='Ada', email='ada@test.org', passwd='A-12345', last_modified=time.time())
	>>> u2 = dict(id=96901, name='Adam', email='adam@test.org', passwd='A-12345', last_modified=time.time())
	>>> insert('user', **u1)
	1
	>>> insert('user', **u2)
	1
	>>> select_int('select count(*) from user')
	5
	>>> select_int('select count(*) from user where email=?', 'ada@test.org')
	1
	>>> select_int('select count(*) from user where email=?', 'notexist@test.org')
	0
	>>> select_int('select id from user where email=?', 'ada@test.org')
	96900
	>>> select_int('select id, name from user where email=?', 'ada@test.org')
	Traceback (most recent call last):
		...
	MultiColumnsError: Expect only one column.
	"""
	d = _select(sql, True, *args)
	if len(d) != 1:
		raise MultiColumnsError('Expect only one column.')
	return d.values()[0]

def select(sql, *args):
	"""
	>>> u1 = dict(id=200, name='Wall.E', email='wall.e@test.org', passwd='back-to-earth', last_modified=time.time())
	>>> u2 = dict(id=201, name='Eva', email='eva@test.org', passwd='back-to-earth', last_modified=time.time())
	>>> insert('user', **u1)
	1
	>>> insert('user', **u2)
	1
	>>> L = select('select * from user where id=?', 900900900)
	>>> L
	[]
	>>> L = select('select * from user where id=?', 200)
	>>> L[0].email
	u'wall.e@test.org'
	>>> L = select('select * from user where passwd=? order by id desc', 'back-to-earth')
	>>> L[0].name
	u'Eva'
	>>> L[1].name
	u'Wall.E'
	"""
	return _select(sql, False, *args)

@with_connection
def _update(sql, *args):
	"""
	execute update statement, return columns
	"""
	global _db_ctx
	cursor = None
	sql = sql.replace('?', '%s')
	logging.info('SQL:%s, ARGS:%s' % (sql, args))
	try:
		cursor = _db_ctx.connection.cursor()
		cursor.execute(sql, args)
		r = cursor.rowcount
		if _db_ctx.transactions == 0:
			logging.info('auto commit')
			_db_ctx.connection.commit()
		return r
	finally:
		if cursor:
			cursor.close()

def update(sql, *args):
	"""
	>>> u1 = dict(id=1000, name='Michael', email='michael@test.org', passwd='123456', last_modified=time.time())
	>>> insert('user', **u1)
	1
	>>> u2 = select_one('select * from user where id=?', 1000)
	>>> u2.email
	u'michael@test.org'
	>>> u2.passwd
	u'123456'
	>>> update('update user set email=?, passwd=? where id=?', 'michael@example.org', '654321', 1000)
	1
	>>> u3 = select_one('select * from user where id=?', 1000)
	>>> u3.email
	u'michael@example.org'
	>>> u3.passwd
	u'654321'
	>>> update('update user set passwd=? where id=?', '***', '123')
	0
	"""
	return _update(sql, *args)

def insert(table, **kw):
	"""
	execute insert statement
	>>> u1 = dict(id=2000, name='Bob', email='bob@test.org', passwd='bobobob', last_modified=time.time())
	>>> insert('user', **u1)
	1
	>>> u2 = select_one('select * from user where id=?', 2000)
	>>> u2.name
	u'Bob'
	>>> insert('user', **u2)
	Traceback (most recent call last):
	  ...
	IntegrityError: 1062 (23000): Duplicate entry '2000' for key 'PRIMARY'
	"""
	cols, args = zip(*kw.iteritems())
	sql = 'insert into `%s` (%s) values (%s)' % (table, ','.join(['`%s`' % col for col in cols]), ','.join(['?' for i in range(len(cols))]))
	return _update(sql, *args)
	
if __name__ == '__main__':
	logging.basicConfig(level=logging.DEBUG)
	create_engine('www-data', 'www-data', 'test', '127.0.0.1')
	update('drop table if exists user')
	update('create table user (id int primary key, name text, email text, passwd text, last_modified real)')
	import doctest
	doctest.testmod()
