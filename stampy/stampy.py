#!/usr/bin/env python
# encoding: utf-8
#
# Description: Bot for controlling karma on Telegram
# Author: Pablo Iranzo Gomez (Pablo.Iranzo@gmail.com)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.   See the
# GNU General Public License for more details.

import datetime
import json
import logging
import optparse
import sqlite3 as lite
import string
import sys
import urllib
from time import sleep

from apscheduler.schedulers.background import BackgroundScheduler

import plugins
import plugin.config


description = """
Stampy is a script for controlling Karma via Telegram.org bot api

"""

# Option parsing
p = optparse.OptionParser("stampy.py [arguments]", description=description)
p.add_option("-t", "--token", dest="token",
             help="API token for bot access to messages", default=False)
p.add_option("-b", "--database", dest="database",
             help="database file for storing karma and last processed message",
             default="stampy.db")
p.add_option('-v', "--verbosity", dest="verbosity",
             help="Set verbosity level for messages while running/logging",
             default=0, type='choice',
             choices=["info", "debug", "warn", "critical"])
p.add_option('-u', "--url", dest="url",
             help="Define URL for accessing bot API",
             default="https://api.telegram.org/bot")
p.add_option('-o', '--owner', dest='owner',
             help="Define owner username for monitoring service",
             default="iranzo")
p.add_option('-d', '--daemon', dest='daemon', help="Run as daemon",
             default=False, action="store_true")

(options, args) = p.parse_args()


# Set scheduler
scheduler = BackgroundScheduler()
scheduler.start()


# Implement switch from http://code.activestate.com/recipes/410692/
class Switch(object):
    """
    Defines a class that can be used easily as traditional switch commands
    """

    def __init__(self, value):
        self.value = value
        self.fall = False

    def __iter__(self):
        """Return the match method once, then stop"""
        yield self.match
        raise StopIteration

    def match(self, *args):
        """Indicate whether or not to enter a case suite"""
        if self.fall or not args:
            return True
        elif self.value in args:  # changed for v1.5, see below
            self.fall = True
            return True
        else:
            return False


def createdb():
    """
    Create database if it doesn't exist
    :return:
    """
    con = lite.connect(options.database)
    cur = con.cursor()
    cur.execute('CREATE TABLE karma(word TEXT, value INT);')
    cur.execute('CREATE TABLE alias(key TEXT, value TEXT);')
    cur.execute('CREATE TABLE autokarma(key TEXT, value TEXT);')
    cur.execute('CREATE TABLE config(key TEXT, value TEXT);')
    cmd = 'CREATE TABLE stats(type TEXT, id INT, name TEXT, date TEXT, \
          count INT, memberid TEXT);'
    cur.execute(cmd)
    cmd = 'CREATE TABLE quote(id INTEGER PRIMARY KEY AUTOINCREMENT,  \
         username TEXT, date TEXT, text TEXT);'
    cur.execute(cmd)
    return


# Function definition
def dbsql(sql=False):
    """
    Performs SQL operation on database
    :param sql: sql command to execute
    :return:
    """
    logger = logging.getLogger(__name__)

    # Initialize database access
    con = False
    try:
        con = lite.connect(options.database)
        cur = con.cursor()
        cur.execute("SELECT * FROM config WHERE key='token';")
        cur.fetchone()

    except lite.Error, e:
        createdb()
        logger.debug(msg="Error %s:" % e.args[0])
        logger.debug(msg="DB has been created, continuing")
        con = lite.connect(options.database)
        cur = con.cursor()
        cur.execute("SELECT * FROM config WHERE key='token';")
        cur.fetchone()

    # Database initialized

    worked = False
    if sql:
        try:
            cur.execute(sql)
            con.commit()
            worked = True
        except:
            worked = False
    if not worked:
        logger.critical(msg="Error on SQL execution: %s" % sql)

    return cur


def sendmessage(chat_id=0, text="", reply_to_message_id=False,
                disable_web_page_preview=True, parse_mode=False,
                extra=False):
    """
    Sends a message to a chat
    :param chat_id: chat_id to receive the message
    :param text: message text
    :param reply_to_message_id: message_id to reply
    :param disable_web_page_preview: do not expand links to include preview
    :param parse_mode: use specific format (markdown, html)
    :param extra: extra parameters to send
                 (for future functions like keyboard_markup)
    :return:
    """

    logger = logging.getLogger(__name__)
    url = "%s%s/sendMessage" % (plugin.config.config(key="url"),
                                plugin.config.config(key='token'))
    lines = text.split("\n")
    maxlines = 15
    if len(lines) > maxlines:
        # message might be too big for single message (max 4K)
        if "```" in text:
            markdown = True
        else:
            markdown = False

        texto = string.join(lines[0:maxlines], "\n")
        if markdown:
            texto = "%s```" % texto

        # Send first batch
        sendmessage(chat_id=chat_id, text=texto,
                    reply_to_message_id=reply_to_message_id,
                    disable_web_page_preview=disable_web_page_preview,
                    parse_mode=parse_mode, extra=extra)
        # Send remaining batch
        texto = string.join(lines[maxlines:], "\n")
        if markdown:
            texto = "```%s" % texto
        sendmessage(chat_id=chat_id, text=texto, reply_to_message_id=False,
                    disable_web_page_preview=disable_web_page_preview,
                    parse_mode=parse_mode, extra=extra)
        return

    message = "%s?chat_id=%s&text=%s" % (
              url, chat_id, urllib.quote_plus(text.encode('utf-8')))
    if reply_to_message_id:
        message += "&reply_to_message_id=%s" % reply_to_message_id
    if disable_web_page_preview:
        message += "&disable_web_page_preview=1"
    if parse_mode:
        message += "&parse_mode=%s" % parse_mode
    if extra:
        message += "&%s" % extra

    code = False
    attempt = 0
    while not code:
        result = json.load(urllib.urlopen(message))
        code = result['ok']
        logger.error(msg="ERROR (%s) sending message: Code: %s : Text: %s" % (
                         attempt, code, result))
        attempt = attempt + 1
        sleep(1)
        # exit after 60 retries with 1 second delay each
        if attempt > 60:
            logger.error(msg="PERM ERROR sending message: Code: %s : Text: "
                             "%s" % (code, result))
            code = True
    logger.debug(msg="Sending message: Code: %s : Text: %s" % (code, text))
    return


def getupdates(offset=0, limit=100):
    """
    Gets updates (new messages from server)
    :param offset: last update id
    :param limit: maximum number of messages to gather
    :return: returns the items obtained
    """

    logger = logging.getLogger(__name__)
    url = "%s%s/getUpdates" % (plugin.config.config(key='url'),
                               plugin.config.config(key='token'))
    message = "%s?" % url
    if offset != 0:
        message += "offset=%s&" % offset
    message += "limit=%s" % limit
    try:
        result = json.load(urllib.urlopen(message))['result']
    except:
        result = []
    for item in result:
        logger.info(msg="Getting updates and returning: %s" % item)
        yield item


def clearupdates(offset):
    """
    Marks updates as already processed so they are removed by API
    :param offset:
    :return:
    """

    logger = logging.getLogger(__name__)
    url = "%s%s/getUpdates" % (plugin.config.config(key='url'), plugin.config.config(key='token'))
    message = "%s?" % url
    message += "offset=%s&" % offset
    try:
        result = json.load(urllib.urlopen(message))
    except:
        result = False
    logger.info(msg="Clearing messages")
    return result


def telegramcommands(texto, chat_id, message_id, who_un):
    """
    Processes telegram commands in message texts (/help, etc)
    :param texto: text from the update
    :param chat_id:  chat to answer to
    :param message_id: message to reply to
    :param who_un: username of user providing the command
    :return: True if any telegramcommands where processed,
             False if no telegramcommands were present
    """

    logger = logging.getLogger(__name__)

    # Process lines for commands in the first word of the line (Telegram)
    if texto:
        word = texto.split()[0]
    else:
        texto = ""
        word = ""
    if "@" in word:
        # If the message is directed as /help@bot, remove that part
        word = word.split("@")[0]

    commandtext = False
    retv = False
    for case in Switch(word):
        if case('/help'):
            if plugin.config.config(key='owner') == who_un:
                commandtext += "Use `/quit` to exit daemon mode\n"
                commandtext += "Learn more about this bot in " \
                               "[https://github.com/iranzo/stampython]" \
                               "(https://github.com/iranzo/stampython)"
            break
        if case('/start'):
            commandtext = "This bot does not use start or stop commands,"
            commandtext += " it automatically checks for karma operands"
            retv = True
            break
        if case('/stop'):
            commandtext = "This bot does not use start or stop commands, "
            commandtext += "it automatically checks for karma operands"
            retv = True
            break
        if case('/quit'):
            # Disable running as daemon to ensure we're exiting the loop
            if plugin.config.config(key='owner') == who_un:
                plugin.config.setconfig('daemon', False)
            retv = True

        if case():
            commandtext = False

    # If any of above commands did match, send command
    if commandtext:
        sendmessage(chat_id=chat_id, text=commandtext,
                    reply_to_message_id=message_id, parse_mode="Markdown")
        logger.debug(msg="Command: %s" % word)
    return retv


def sendsticker(chat_id=0, sticker="", text="", reply_to_message_id=""):
    """
    Sends a sticker to chat_id as a reply to a message received
    :param chat_id: ID of the chat
    :param sticker: Sticker identification
    :param text: Additional text
    :param reply_to_message_id:
    :return:
    """

    logger = logging.getLogger(__name__)
    url = "%s%s/sendSticker" % (plugin.config.config(key='url'), plugin.config.config(key='token'))
    message = "%s?chat_id=%s" % (url, chat_id)
    message = "%s&sticker=%s" % (message, sticker)
    if reply_to_message_id:
        message += "&reply_to_message_id=%s" % reply_to_message_id
    logger.debug(msg="Sending sticker: %s" % text)
    return json.load(urllib.urlopen(message))


def sendimage(chat_id=0, image="", text="", reply_to_message_id=""):
    """
    Sends an image to chat_id as a reply to a message received
    :param chat_id: ID of the chat
    :param image: image URI
    :param text: Additional text or caption
    :param reply_to_message_id:
    :return:
    """

    logger = logging.getLogger(__name__)
    url = "%s%s/sendPhoto" % (plugin.config.config(key='url'), plugin.config.config(key='token'))
    message = "%s?chat_id=%s" % (url, chat_id)
    message = "%s&photo=%s" % (message, image)
    if reply_to_message_id:
        message += "&reply_to_message_id=%s" % reply_to_message_id
    if text:
        message += "&caption=%s" % urllib.quote_plus(text.encode('utf-8'))
    logger.debug(msg="Sending image: %s" % text)
    return json.load(urllib.urlopen(message))


def replace_all(text, dictionary):
    """
    Replaces text with the dict
    :param text: Text to process
    :param dictionary:  The dictionary of replacements
    :return: the modified text
    """

    for i, j in dictionary.iteritems():
        text = text.replace(i, j)
    return text


def getmsgdetail(message):
    """
    Gets message details and returns them as dict
    :param message: message to get details from
    :return: message details as dict
    """

    try:
        update_id = message['update_id']
    except:
        update_id = ""

    type = ""

    try:
        # Regular message
        chat_id = message['message']['chat']['id']
        type = "message"
    except:
        try:
            # Message in a channel
            chat_id = message['channel_post']['chat']['id']
            type = "channel_post"
        except:
            chat_id = ""

    try:
        chat_name = message[type]['chat']['title']
    except:
        chat_name = ""

    try:
        text = message[type]['text']
    except:
        text = ""

    try:
        message_id = int(message[type]['message_id'])
        date = int(float(message[type]['date']))
        datefor = datetime.datetime.fromtimestamp(float(date)).strftime('%Y-%m-%d %H:%M:%S')
        who_gn = message[type]['from']['first_name']
        who_id = message[type]['from']['id']
        error = False
    except:
        error = True
        who_id = ""
        who_gn = ""
        date = ""
        datefor = ""
        message_id = ""

    try:
        who_ln = message[type]['from']['last_name']
    except:
        who_ln = ""

    # Some user might not have username defined so this
    # was failing and message was ignored
    try:
        who_un = message[type]['from']['username']
    except:
        who_un = ""

    name = "%s %s (@%s)" % (who_gn, who_ln, who_un)

    # args = ('name', 'chat_id', 'chat_name', 'date', 'datefor', 'error', 'message_id',
    #         'text', 'update_id', 'who_gn', 'who_id', 'who_ln', 'who_un')
    # vals = dict((k, v) for (k, v) in locals().iteritems() if k in args)

    vals = {"name": name, "chat_id": chat_id, "chat_name": chat_name, "date": date, "datefor": datefor, "error": error,
            "message_id": message_id, "text": text, "update_id": update_id, "who_gn": who_gn, "who_id": who_id,
            "who_ln": who_ln, "who_un": who_un, "type": type}

    return vals


def process(messages):
    """
    This function processes the updates in the Updates URL at Telegram
    for finding commands, karma changes, config, etc
    """

    logger = logging.getLogger(__name__)

    # check if Log level has changed
    loglevel()

    # Main code for processing the karma updates
    date = 0
    lastupdateid = 0
    logger.info(msg="Initial message at %s" % date)
    texto = ""
    count = 0

    # Process each message available in URL and search for karma operators
    for message in messages:
        # Count messages in each batch
        count += 1

        # Call plugins to process message
        for i in plugins.getPlugins():
            logger.debug(msg="Processing plugin: %s" % i["name"])
            plug = plugins.loadPlugin(i)
            plug.run(message=message)

        msgdetail = getmsgdetail(message)

        # Update last message id to later clear it from the server
        if msgdetail["update_id"] > lastupdateid:
            lastupdateid = msgdetail["update_id"]

        # Write the line for debug
        messageline = "TEXT: %s : %s : %s" % (msgdetail["chat_name"], msgdetail["name"], msgdetail["text"])
        texto = msgdetail["text"]
        logger.debug(msg=messageline)

    logger.info(msg="Last processed message at: %s" % date)
    logger.debug(msg="Last processed update_id : %s" % lastupdateid)
    logger.debug(msg="Last processed text: %s" % texto)
    logger.info(msg="Number of messages in this batch: %s" % count)

    # clear updates (marking messages as read)
    clearupdates(offset=lastupdateid + 1)


def loglevel():
    """
    This functions stores or sets the proper log level based on the
    database configuration
    """

    logger = logging.getLogger(__name__)
    level = False

    for case in Switch(plugin.config.config(key="verbosity").lower()):
        # choices=["info", "debug", "warn", "critical"])
        if case('debug'):
            level = logging.DEBUG
            break
        if case('critical'):
            level = logging.CRITICAL
            break
        if case('warn'):
            level = logging.WARN
            break
        if case('info'):
            level = logging.INFO
            break
        if case():
            # Default to DEBUG log level
            level = logging.DEBUG

    # If logging level has changed, redefine in logger,
    # database and send message
    if logging.getLevelName(logger.level).lower() != plugin.config.config(key="verbosity"):
        logger.setLevel(level)
        logger.info(msg="Logging level set to %s" % plugin.config.config(key="verbosity"))
        plugin.config.setconfig(key="verbosity",
                                value=logging.getLevelName(logger.level).lower())
    else:
        logger.debug(msg="Log level didn't changed from %s" % (
                         plugin.config.config(key="verbosity").lower()))


def conflogging():
    """
    This function configures the logging handlers for console and file
    """

    logger = logging.getLogger(__name__)

    # Define logging settings
    if not plugin.config.config(key="verbosity"):
        if not options.verbosity:
            # If we don't have defined command line value and it's not stored,
            # use DEBUG
            plugin.config.setconfig(key="verbosity", value="DEBUG")
        else:
            plugin.config.setconfig(key="verbosity", value=options.verbosity)

    loglevel()

    # create formatter
    formatter = logging.Formatter('%(asctime)s : %(name)s : %(funcName)s(%(lineno)d) : %(levelname)s : %(message)s')

    # create console handler and set level to debug
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # create file logger
    filename = '%s.log' % plugin.config.config(key='database').split(".")[0]

    file = logging.FileHandler(filename)
    file.setLevel(logging.DEBUG)
    file.setFormatter(formatter)
    logger.addHandler(file)

    return


def main():
    """
    Main code for the bot
    """

    # Main code
    logger = logging.getLogger(__name__)

    # Set database name in config
    if options.database:
        plugin.config.setconfig(key='database', value=options.database)

    if not logger.handlers:
        conflogging()

    logger.info(msg="Started execution")

    if not plugin.config.config(key='sleep'):
        plugin.config.setconfig(key='sleep', value=10)

    # Check if we've the token required to access or exit
    if not plugin.config.config(key='token'):
        if options.token:
            token = options.token
            plugin.config.setconfig(key='token', value=token)
        else:
            msg = "Token required for operation, please check"
            msg += " https://core.telegram.org/bots"
            logger.critical(msg)
            sys.exit(1)

    # Check if we've URL defined on DB or on cli and store
    if not plugin.config.config(key='url'):
        if options.url:
            plugin.config.setconfig(key='url', value=options.url)

    # Check if we've owner defined in DB or on cli and store
    if not plugin.config.config(key='owner'):
        if options.owner:
            plugin.config.setconfig(key='owner', value=options.owner)

    # Initialize modules
    for i in plugins.getPlugins():
        logger.debug(msg="Processing plugin initialization: %s" % i["name"])
        plug = plugins.loadPlugin(i)
        plug.init()

    # Check operation mode and call process as required
    if options.daemon or plugin.config.config(key='daemon'):
        plugin.config.setconfig(key='daemon', value=True)
        logger.info(msg="Running in daemon mode")
        while plugin.config.config(key='daemon') == 'True':
            process(getupdates())
            sleep(int(plugin.config.config(key='sleep')))
    else:
        logger.info(msg="Running in one-shoot mode")
        process(getupdates())

    logger.info(msg="Stopped execution")
    logging.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    # Set name to the database being used to allow multibot execution
    if plugin.config.config(key="database"):
        __name__ = plugin.config.config(key="database").split(".")[0]
    else:
        plugin.config.setconfig(key="database", value='stampy')
        __name__ = "stampy"
    main()
