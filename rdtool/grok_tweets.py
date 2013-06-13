# rdtool/grok_tweets.py

#
# Copyright (c) 2013 Simone Basso <bassosimone@gmail.com>
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

""" Grok tweets looking for blog posts """

import email.utils
import getopt
import json
import logging
import os
import random
import re
import sys
import textwrap
import time
import urlparse

if __name__ == "__main__":
    sys.path.insert(0, ".")

from rdtool import subr_bitly
from rdtool import subr_http
from rdtool import subr_misc
from rdtool import subr_prompt

DEFERRED_TWEETS = []

SETTINGS = {
            "force": False,
           }

#
# [Wed May 15 14:18:49 +0000 2013]
# <https://twitter.com/arduinoallinclu/status/334674230635548672>
# @arduinoallinclu: @RivoluzDigitale Nuovo articolo di @SoFranchy:
# "#Stampa_3D e #makers: una terza rivoluzione industriale?" Leggi:
# http://t.co/Kj7EhkXNMn
#

def tweet_ctime(tweet):
    """ Get the time when the tweet was created """
    if not tweet.startswith("["):
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    index = tweet.find("]")
    if index == -1:
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    when = tweet[1:index]
    return email.utils.parsedate(when)

def tweet_id(tweet):
    """ Get the identifier of the tweet """
    index = tweet.find("<")
    if index == -1:
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    tweet = tweet[index + 1:]
    index = tweet.find(">")
    if index == -1:
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    tweet = tweet[:index]
    if not tweet.startswith("https://twitter.com/"):
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    index = tweet.find("/status/")
    if index == -1:
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    tweet = tweet[index + len("/status/"):]
    return int(tweet)

def tweet_account(tweet):
    """ Get the account that generated the tweet """
    index = tweet.find(">")
    if index == -1:
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    tweet = tweet[index + 1:]
    index = tweet.find(":")
    if index == -1:
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    return tweet[:index].strip().lower()

def tweet_text(tweet):
    """ Get the text of the tweet """
    index = tweet.find(">")
    if index == -1:
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    tweet = tweet[index + 1:]
    index = tweet.find(":")
    if index == -1:
        logging.warning("grok_tweets: invalid tweet: %s", tweet)
        return
    return tweet[index + 1:].strip()

def analyze_tweet(students, text, links, handles, tags):
    """ Analyze tweet text and fill links, handles and tags """

    text = text.replace("http://t.co/", "__t_c_o__")
    text = text.replace("https://t.co/", "__t_c_o__")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace(";", " ")
    text = text.replace(",", " ")
    text = text.replace(".", " ")
    text = text.replace(":", " ")
    text = text.replace("!", " ")
    text = text.replace("\"", " ")
    text = text.replace("/", " ")
    text = text.replace("__t_c_o__", "http://t.co/")  # Force http
    text = text.split()

    for elem in text:
        if elem.startswith("http://t.co"):  # We forced http above
            elem = elem.replace("http://t.co", "")
            links.append(elem)
        elif elem.startswith("@"):
            elem = elem.lower()
            if elem[1:] in students:
                handles.append(elem)
        elif elem.startswith("#"):
            elem = elem.lower()
            tags.append(elem)

def save_tweet(prefix, timest, student, real_link, bodyvec):
    """ Save a tweet """

    # Pause a bit before the download so we sleep in any case
    time.sleep(random.random() + 0.5)

    bitlink = subr_bitly.shorten(real_link[0])
    bitlink = bitlink.replace("http://bit.ly/", "")
    bitlink = bitlink.replace("https://bit.ly/", "")

    if not re.search("^[A-Za-z0-9]+$", bitlink):
        logging.warning("grok_tweets: invalid bitlink <%s>; skip", bitlink)
        return

    dirpath = os.sep.join([prefix, student, bitlink])
    if os.path.isdir(dirpath):
        logging.warning("grok_tweets: dup <%s>; skip", dirpath)
        return

    subr_misc.mkdir_recursive_idempotent(dirpath)

    filepath = os.sep.join([dirpath, "%04d-%02d-%02d.html" % (
      timest[0], timest[1], timest[2])])

    filep = open(filepath, "w")
    for chunk in bodyvec:
        filep.write(chunk)
    filep.close()

def process_tweet(prefix, students, blogs, timest, account, text):
    """ Process a tweet """

    links = []
    handles = []
    tags = []
    if account[1:] in students:  # handles do not start with @
        handles.append(account)
    analyze_tweet(students, text, links, handles, tags)

    handles = list(set(handles))  # collapse duplicates, if needed
    for handle in handles:
        handle = handle[1:]  # Skip either @ or #
        student = students.get(handle)
        if not student:
            logging.warning("grok_tweets: cannot find student from %s", handle)
            continue
        process_student_tweet(prefix, blogs, timest, account, text, links,
                               handle, student)

def process_student_tweet(prefix, blogs, timest, account, text, links,
                           handle, student):
    """ Process a tweet from the point of view of one student """

    # Pause a bit before the download so we sleep in any case
    time.sleep(random.random() + 0.5)

    # Expand links before possibly prompting the operator
    new_links = []
    for link in links:
        expanded_link = []
        result = subr_http.retrieve("HEAD", "http", "t.co", link, [],
          expanded_link)
        if result == 200:
            new_links.append(expanded_link[0])
    links = new_links

    index = subr_prompt.select_one("link", links)
    if index < 0:
        logging.warning("grok_tweets: deferring decision")
        tweet = ": ".join([account, text])
        DEFERRED_TWEETS.append(tweet)
        return
    link = links[index]

    # Pause a bit before the download so we sleep in any case
    time.sleep(random.random() + 0.5)

    parsed = urlparse.urlsplit(link)
    bodyvec = []
    real_link = []
    result = subr_http.retrieve("GET", parsed[0], parsed[1], parsed[2],
      bodyvec, real_link)
    if result != 200:
        return

    base_url = blogs[handle]
    if not base_url:
        logging.warning("grok_tweets: cannot find url from %s", handle)
        return
    if base_url not in real_link[0]:
        logging.warning("grok_tweets: foreign link <%s>; skip", real_link[0])
        return

    parsed = urlparse.urlsplit(real_link[0])
    if not parsed[2] or parsed[2] == "/":
        logging.warning("grok_tweets: homepage link <%s>; skip", real_link[0])
        return

    # Otherwise there are cases of duplicate posts
    index = real_link[0].rfind("?")
    if index >= 0:
        real_link[0] = real_link[0][:index]

    save_tweet(prefix, timest, student, real_link, bodyvec)

def really_filter_tweet(prefix, students, blogs, timest, account, text):
    """ Really filter a tweet """

    if text.startswith("RT "):
        logging.warning("grok_tweets: skip RT")
        return
    if "@rivoluzdigitale" not in text.lower():
        logging.warning("grok_tweets: does not mention @RivoluzDigitale; skip")
        return
    if not "t.co/" in text.lower():
        logging.warning("grok_tweets: does not include links; skip")
        return

    process_tweet(prefix, students, blogs, timest, account, text)

def filter_tweet(prefix, students, blogs, tweet):
    """ Filter a tweet """

    sys.stdout.write("\n\n\n")
    for line in textwrap.wrap(tweet):
        sys.stdout.write("    %s\n" % line)
    sys.stdout.write("\n")

    timest = tweet_ctime(tweet)
    twid = tweet_id(tweet)
    account = tweet_account(tweet)
    text = tweet_text(tweet)

    statedir = os.sep.join([os.environ.get("HOME", "/"), ".grok_tweets"])
    statefile = os.sep.join([statedir, account[1:]])

    prev = 0
    if not SETTINGS["force"] and os.path.isfile(statefile):
        filep = open(statefile, "r")
        data = filep.read()
        filep.close()
        try:
            prev = int(data.strip())
        except ValueError:
            pass

    if twid > prev:
        really_filter_tweet(prefix, students, blogs, timest, account, text)

        if not SETTINGS["force"] and os.path.isdir(statedir):
            filep = open(statefile, "w")
            filep.write(str(twid))
            filep.write("\n")
            filep.close()

    else:
        logging.warning("grok_tweets: old tweet <%d>; skip", twid)

def filter_tweet_safe(prefix, students, blogs, tweet):
    """ Filter a tweet """
    try:
        filter_tweet(prefix, students, blogs, tweet)
    except KeyboardInterrupt:
        sys.exit(1)
    except:
        raise

def main():
    """ Main function """

    level = logging.WARNING
    try:
        options, arguments = getopt.getopt(sys.argv[1:], "d:fv")
    except getopt.error:
        sys.exit("usage: grok_tweets [-fv] [-d directory] file...")
    if not arguments:
        sys.exit("usage: grok_tweets [-fv] [-d directory] file...")
    prefix = "."
    for name, value in options:
        if name == "-d":
            prefix = value
        elif name == "-f":
            SETTINGS["force"] = True
        elif name == "-v":
            level = logging.DEBUG

    logging.basicConfig(level=level, format="%(message)s")

    logging.info("grok_tweets: open config files...")
    filep = open("etc/twitter/students.json", "r")
    students = json.load(filep)
    filep.close()
    filep = open("etc/twitter/blogs.json", "r")
    blogs = json.load(filep)
    filep.close()
    logging.info("grok_tweets: open config files... done")

    for argument in arguments:
        filep = open(argument, "r")
        vector = []
        for line in filep:
            line = line.strip()
            if not line:
                if not vector:
                    continue
                tweet = " ".join(vector)
                tweet = re.sub(r"[\0-\31]", " ", tweet)
                tweet = re.sub(r"[\x7f-\xff]", " ", tweet)
                filter_tweet_safe(prefix, students, blogs, tweet)
                vector = []
                continue
            vector.append(line)

    if DEFERRED_TWEETS:
        sys.stdout.write("\n\n\n====== BEGIN DEFERRED TWEETS ======\n\n")
        for tweet in DEFERRED_TWEETS:
            for line in textwrap.wrap(tweet):
                sys.stdout.write("    %s\n" % line)
            sys.stdout.write("\n")
        sys.stdout.write("====== END DEFERRED TWEETS ======\n\n")

if __name__ == "__main__":
    main()
