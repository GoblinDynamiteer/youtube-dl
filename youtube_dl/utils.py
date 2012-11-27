#!/usr/bin/env python
# -*- coding: utf-8 -*-

import gzip
import locale
import os
import re
import sys
import zlib
import email.utils
import json

try:
	import cStringIO as StringIO
except ImportError:
	import StringIO

try:
	import urllib.request as compat_urllib_request
except ImportError: # Python 2
	import urllib2 as compat_urllib_request

try:
	import urllib.error as compat_urllib_error
except ImportError: # Python 2
	import urllib2 as compat_urllib_error

try:
	import urllib.parse as compat_urllib_parse
except ImportError: # Python 2
	import urllib as compat_urllib_parse

try:
	import http.cookiejar as compat_cookiejar
except ImportError: # Python 2
	import cookielib as compat_cookiejar

try:
	import html.entities as compat_html_entities
except NameError: # Python 2
	import htmlentitydefs as compat_html_entities

try:
	import html.parser as compat_html_parser
except NameError: # Python 2
	import HTMLParser as compat_html_parser

try:
	compat_str = unicode # Python 2
except NameError:
	compat_str = str

try:
	compat_chr = unichr # Python 2
except NameError:
	compat_chr = chr


std_headers = {
	'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:10.0) Gecko/20100101 Firefox/10.0',
	'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
	'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
	'Accept-Encoding': 'gzip, deflate',
	'Accept-Language': 'en-us,en;q=0.5',
}
def preferredencoding():
	"""Get preferred encoding.

	Returns the best encoding scheme for the system, based on
	locale.getpreferredencoding() and some further tweaks.
	"""
	try:
		pref = locale.getpreferredencoding()
		u'TEST'.encode(pref)
	except:
		pref = 'UTF-8'

	return pref


def htmlentity_transform(matchobj):
	"""Transforms an HTML entity to a character.

	This function receives a match object and is intended to be used with
	the re.sub() function.
	"""
	entity = matchobj.group(1)

	# Known non-numeric HTML entity
	if entity in compat_html_entities.name2codepoint:
		return compat_chr(compat_html_entities.name2codepoint[entity])

	mobj = re.match(u'(?u)#(x?\\d+)', entity)
	if mobj is not None:
		numstr = mobj.group(1)
		if numstr.startswith(u'x'):
			base = 16
			numstr = u'0%s' % numstr
		else:
			base = 10
		return compat_chr(int(numstr, base))

	# Unknown entity in name, return its literal representation
	return (u'&%s;' % entity)

compat_html_parser.locatestarttagend = re.compile(r"""<[a-zA-Z][-.a-zA-Z0-9:_]*(?:\s+(?:(?<=['"\s])[^\s/>][^\s/=>]*(?:\s*=+\s*(?:'[^']*'|"[^"]*"|(?!['"])[^>\s]*))?\s*)*)?\s*""", re.VERBOSE) # backport bugfix
class IDParser(compat_html_parser.HTMLParser):
	"""Modified HTMLParser that isolates a tag with the specified id"""
	def __init__(self, id):
		self.id = id
		self.result = None
		self.started = False
		self.depth = {}
		self.html = None
		self.watch_startpos = False
		self.error_count = 0
		compat_html_parser.HTMLParser.__init__(self)

	def error(self, message):
		if self.error_count > 10 or self.started:
			raise compat_html_parser.HTMLParseError(message, self.getpos())
		self.rawdata = '\n'.join(self.html.split('\n')[self.getpos()[0]:]) # skip one line
		self.error_count += 1
		self.goahead(1)

	def loads(self, html):
		self.html = html
		self.feed(html)
		self.close()

	def handle_starttag(self, tag, attrs):
		attrs = dict(attrs)
		if self.started:
			self.find_startpos(None)
		if 'id' in attrs and attrs['id'] == self.id:
			self.result = [tag]
			self.started = True
			self.watch_startpos = True
		if self.started:
			if not tag in self.depth: self.depth[tag] = 0
			self.depth[tag] += 1

	def handle_endtag(self, tag):
		if self.started:
			if tag in self.depth: self.depth[tag] -= 1
			if self.depth[self.result[0]] == 0:
				self.started = False
				self.result.append(self.getpos())

	def find_startpos(self, x):
		"""Needed to put the start position of the result (self.result[1])
		after the opening tag with the requested id"""
		if self.watch_startpos:
			self.watch_startpos = False
			self.result.append(self.getpos())
	handle_entityref = handle_charref = handle_data = handle_comment = \
	handle_decl = handle_pi = unknown_decl = find_startpos

	def get_result(self):
		if self.result is None:
			return None
		if len(self.result) != 3:
			return None
		lines = self.html.split('\n')
		lines = lines[self.result[1][0]-1:self.result[2][0]]
		lines[0] = lines[0][self.result[1][1]:]
		if len(lines) == 1:
			lines[-1] = lines[-1][:self.result[2][1]-self.result[1][1]]
		lines[-1] = lines[-1][:self.result[2][1]]
		return '\n'.join(lines).strip()

def get_element_by_id(id, html):
	"""Return the content of the tag with the specified id in the passed HTML document"""
	parser = IDParser(id)
	try:
		parser.loads(html)
	except compat_html_parser.HTMLParseError:
		pass
	return parser.get_result()


def clean_html(html):
	"""Clean an HTML snippet into a readable string"""
	# Newline vs <br />
	html = html.replace('\n', ' ')
	html = re.sub('\s*<\s*br\s*/?\s*>\s*', '\n', html)
	# Strip html tags
	html = re.sub('<.*?>', '', html)
	# Replace html entities
	html = unescapeHTML(html)
	return html


def sanitize_open(filename, open_mode):
	"""Try to open the given filename, and slightly tweak it if this fails.

	Attempts to open the given filename. If this fails, it tries to change
	the filename slightly, step by step, until it's either able to open it
	or it fails and raises a final exception, like the standard open()
	function.

	It returns the tuple (stream, definitive_file_name).
	"""
	try:
		if filename == u'-':
			if sys.platform == 'win32':
				import msvcrt
				msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
			return (sys.stdout, filename)
		stream = open(encodeFilename(filename), open_mode)
		return (stream, filename)
	except (IOError, OSError) as err:
		# In case of error, try to remove win32 forbidden chars
		filename = re.sub(u'[/<>:"\\|\\\\?\\*]', u'#', filename)

		# An exception here should be caught in the caller
		stream = open(encodeFilename(filename), open_mode)
		return (stream, filename)


def timeconvert(timestr):
	"""Convert RFC 2822 defined time string into system timestamp"""
	timestamp = None
	timetuple = email.utils.parsedate_tz(timestr)
	if timetuple is not None:
		timestamp = email.utils.mktime_tz(timetuple)
	return timestamp

def sanitize_filename(s, restricted=False):
	"""Sanitizes a string so it could be used as part of a filename.
	If restricted is set, use a stricter subset of allowed characters.
	"""
	def replace_insane(char):
		if char == '?' or ord(char) < 32 or ord(char) == 127:
			return ''
		elif char == '"':
			return '' if restricted else '\''
		elif char == ':':
			return '_-' if restricted else ' -'
		elif char in '\\/|*<>':
			return '_'
		if restricted and (char in '!&\'' or char.isspace()):
			return '_'
		if restricted and ord(char) > 127:
			return '_'
		return char

	result = u''.join(map(replace_insane, s))
	while '__' in result:
		result = result.replace('__', '_')
	result = result.strip('_')
	# Common case of "Foreign band name - English song title"
	if restricted and result.startswith('-_'):
		result = result[2:]
	if not result:
		result = '_'
	return result

def orderedSet(iterable):
	""" Remove all duplicates from the input iterable """
	res = []
	for el in iterable:
		if el not in res:
			res.append(el)
	return res

def unescapeHTML(s):
	"""
	@param s a string
	"""
	assert type(s) == type(u'')

	result = re.sub(u'(?u)&(.+?);', htmlentity_transform, s)
	return result

def encodeFilename(s):
	"""
	@param s The name of the file
	"""

	assert type(s) == type(u'')

	if sys.platform == 'win32' and sys.getwindowsversion()[0] >= 5:
		# Pass u'' directly to use Unicode APIs on Windows 2000 and up
		# (Detecting Windows NT 4 is tricky because 'major >= 4' would
		# match Windows 9x series as well. Besides, NT 4 is obsolete.)
		return s
	else:
		return s.encode(sys.getfilesystemencoding(), 'ignore')

class DownloadError(Exception):
	"""Download Error exception.

	This exception may be thrown by FileDownloader objects if they are not
	configured to continue on errors. They will contain the appropriate
	error message.
	"""
	pass


class SameFileError(Exception):
	"""Same File exception.

	This exception will be thrown by FileDownloader objects if they detect
	multiple files would have to be downloaded to the same file on disk.
	"""
	pass


class PostProcessingError(Exception):
	"""Post Processing exception.

	This exception may be raised by PostProcessor's .run() method to
	indicate an error in the postprocessing task.
	"""
	pass

class MaxDownloadsReached(Exception):
	""" --max-downloads limit has been reached. """
	pass


class UnavailableVideoError(Exception):
	"""Unavailable Format exception.

	This exception will be thrown when a video is requested
	in a format that is not available for that video.
	"""
	pass


class ContentTooShortError(Exception):
	"""Content Too Short exception.

	This exception may be raised by FileDownloader objects when a file they
	download is too small for what the server announced first, indicating
	the connection was probably interrupted.
	"""
	# Both in bytes
	downloaded = None
	expected = None

	def __init__(self, downloaded, expected):
		self.downloaded = downloaded
		self.expected = expected


class Trouble(Exception):
	"""Trouble helper exception

	This is an exception to be handled with
	FileDownloader.trouble
	"""

class YoutubeDLHandler(compat_urllib_request.HTTPHandler):
	"""Handler for HTTP requests and responses.

	This class, when installed with an OpenerDirector, automatically adds
	the standard headers to every HTTP request and handles gzipped and
	deflated responses from web servers. If compression is to be avoided in
	a particular request, the original request in the program code only has
	to include the HTTP header "Youtubedl-No-Compression", which will be
	removed before making the real request.

	Part of this code was copied from:

	http://techknack.net/python-urllib2-handlers/

	Andrew Rowls, the author of that code, agreed to release it to the
	public domain.
	"""

	@staticmethod
	def deflate(data):
		try:
			return zlib.decompress(data, -zlib.MAX_WBITS)
		except zlib.error:
			return zlib.decompress(data)

	@staticmethod
	def addinfourl_wrapper(stream, headers, url, code):
		if hasattr(compat_urllib_request.addinfourl, 'getcode'):
			return compat_urllib_request.addinfourl(stream, headers, url, code)
		ret = compat_urllib_request.addinfourl(stream, headers, url)
		ret.code = code
		return ret

	def http_request(self, req):
		for h in std_headers:
			if h in req.headers:
				del req.headers[h]
			req.add_header(h, std_headers[h])
		if 'Youtubedl-no-compression' in req.headers:
			if 'Accept-encoding' in req.headers:
				del req.headers['Accept-encoding']
			del req.headers['Youtubedl-no-compression']
		return req

	def http_response(self, req, resp):
		old_resp = resp
		# gzip
		if resp.headers.get('Content-encoding', '') == 'gzip':
			gz = gzip.GzipFile(fileobj=StringIO.StringIO(resp.read()), mode='r')
			resp = self.addinfourl_wrapper(gz, old_resp.headers, old_resp.url, old_resp.code)
			resp.msg = old_resp.msg
		# deflate
		if resp.headers.get('Content-encoding', '') == 'deflate':
			gz = StringIO.StringIO(self.deflate(resp.read()))
			resp = self.addinfourl_wrapper(gz, old_resp.headers, old_resp.url, old_resp.code)
			resp.msg = old_resp.msg
		return resp
