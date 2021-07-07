#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import discum
import json
import hashlib
import base64
import time
import os
import argparse
from urlextract import URLExtract
import configparser
from urllib.parse import urlparse
import validators
import sys
import signal
import newspaper


uuid = "48093b86-8ce5-415b-ac7d-8add427ec49c"
ailfeedertype = "ail_feeder_discord"
ailurlextract = "ail_feeder_urlextract"

# config reader
config = configparser.ConfigParser()
config.read('../etc/ail-feeder-discord.cfg')

t = open("etc/token.txt", "r").read()
client = discum.Client(token=t, log={"console":False, "file":False})


@client.gateway.command
def start(resp):
    # As soon as there is a response with the user being ready, the execution starts
    if resp.event.ready_supplemental:
        user = client.gateway.session.user
        print("Logged in as {}#{}".format(user['username'], user['discriminator']))

        # Scan the servers the user is already on
        servers = client.getGuilds().json()
        print("Scanning the servers the user is on...\n")
        for server in servers:
            scanned_servers.append(server['id'])
            print("Scanning '" + server['name'] + "' now...")
            scanServer(server)
            print("Done scanning '" + server['name'] + "'\n")
        print("Done with the scan of existing servers!")

        print("Sleeping for 5 seconds to avoid rate limits...\n")
        time.sleep(5)
        
        # Once we scanned all the servers the user is already on, we join the ones from server-invite-codes.txt and search those as well
        print("Joining the servers from the server invite codes...\n")
        codes = open("etc/server-invite-codes.txt", "r")
        for code in codes:
            joinServer(code)
        print("Done joining and scanning the given servers!\n")

        # TODO: This will be replaced with the continuous feed of messages check
        print("All done! Exiting now...")
        os._exit(0)
    
    # Continuously check for new messages
    #if resp.event.message:
    #    m = resp.parsed.auto()


def scanServer(server):
    # All possible channel types: 
    # guild_text, dm, guild_voice, group_dm, guild_category, guild_news, guild_store, guild_news_thread, guild_public_thread, guild_private_thread, guild_stage_voice
    # For now we only consider the text channels
    channel_types = ['guild_text', 'dm', 'group_dm', 'guild_news', 'guild_store', 'guild_news_thread', 'guild_public_thread', 'guild_private_thread']
    channels = client.gateway.findVisibleChannels(server['id'], channel_types)

    for channel in channels:
        messages = client.searchMessages(guildID= server['id'], textSearch=args.query).json()
        # Get n messages from the channel
        # messages = client.getMessages(channel, 5).json()
        # print(json.dumps(messages, indent=4))
        if 'messages' in messages:
            for message in messages['messages']:
                signal.alarm(10)
                try:
                    createJson(message[0], server, channel)
                except TimeoutError:
                    print("Timeout reached for search in channel: {}".format(channel['name']), file=sys.stderr)
                    sys.exit(1)
                else:
                    signal.alarm(0)
        
        messages = client.searchMessages(guildID=server['id'], has="link").json()
        # print(json.dumps(messages, indent=4))
        # print("Found " + str(messages['total_results']) + " messages with a URL")
        for message in messages['messages']:
            extractURLs(message[0])


def createJson(message, server, channel):
    # TODO: Check if the message has already been analysed (caching)

    output_message = {}
    
    output_message['source'] = ailfeedertype
    output_message['source-uuid'] = uuid
    output_message['default-encoding'] = 'UTF-8'
    
    output_message['meta'] = {}
    output_message['meta']['message:id'] = message['id']
    output_message['meta']['message:url'] = "https://discord.com/channels/" + server['id'] + "/" + channel + "/" + message['id']

    output_message['meta']['channel:id'] = message['channel_id']
    output_message['meta']['sender:id'] = message['author']['id']
    output_message['meta']['sender:profile'] = message['author']['username'] + "#" + message['author']['discriminator']
    output_message['meta']['server:id'] = server['id']
    output_message['meta']['server:name'] = server['name']

    output_message['meta']['attachments'] = []
    for attachment in message['attachments']:
        a = {}
        a['id'] = attachment['id']
        a['filename'] = attachment['filename']
        a['url'] = attachment['url']
        a['proxy_url'] = attachment['proxy_url']
        a['type'] = attachment['content_type']
        output_message['meta']['attachments'].append(a)

    output_message['meta']['mentions:user'] = []
    for mention in message['mentions']:
        m = {}
        m['id'] = mention['id']
        m['sender:profile'] = mention['username'] + "#" + mention['discriminator']
        output_message['meta']['usermentions'].append(m)

    output_message['meta']['mentions:role'] = []
    for rolemention in message['mention_roles']:
        rm = {}
        rm['role:id'] = rolemention
        output_message['meta']['rolementions'].append(rm)
    
    output_message['meta']['mentions:everyone'] = message['mention_everyone']

    output_message['meta']['reactions'] = []
    if 'reactions' in message:
        for reaction in message['reactions']:
            r = {}
            r['id'] = reaction['emoji']['id']
            r['name'] = reaction['emoji']['name']
            r['count'] = reaction['count']
            output_message['meta']['reactions'].append(r)

    output_message['meta']['timestamp'] = message['timestamp']
    output_message['meta']['edited_timestamp'] = message['edited_timestamp']
    output_message['meta']['webhook:id'] = ''
    if 'webhook_id' in message:
        output_message['meta']['webhook_id'] = message['webhook_id']

    output_message['meta']['embedded-objects'] = []
    for embedded in message['embeds']:
        e = {}
        # All the fields that exist: 
        # title, type, url, description, timestamp, color, footer, image, thumbnail, video, provider, author, fields
        fields = ['title', 'type', 'url', 'description']
        for field in fields:
            if field in embedded:
                e[field] = embedded[field]
        output_message['meta']['embedded-objects'].append(e)

    if 'message_reference' in message:
        output_message['meta']['referenced-message'] = {}
        output_message['meta']['referenced-message']['guild-id'] = message['message_reference']['guild_id']
        output_message['meta']['referenced-message']['channel-id'] = message['message_reference']['channel_id']
        output_message['meta']['referenced-message']['message-id'] = message['message_reference']['message_id']
        output_message['meta']['referenced-message']['url'] = "https://discord.com/channels/" + message['message_reference']['guild_id'] + "/" + message['message_reference']['channel_id'] + "/" + message['message_reference']['message_id']

        if (args.replies):
            referenced_message = client.getMessage(message['message_reference']['channel_id'], message['message_reference']['message_id']).json()
            # print(json.dumps(referenced_message[0], indent=4))
            createJson(referenced_message[0], server, channel)

    #Encoding the content of the message into base64
    content_bytes = message['content'].encode('utf-8')
    output_message['data-sha256'] = hashlib.sha256(content_bytes).hexdigest()
    output_message['data'] = base64.b64encode(content_bytes).decode('utf-8')
    # output_message['message:content'] = message['content']

    print("Found a message which matches the query!")
    print("The JSON of the message is:")
    print(json.dumps(output_message, indent=4, sort_keys=True))
    # TODO: publish to AIL


def extractURLs(message):
    extractor = URLExtract()
    urls = extractor.find_urls(message['content'])
    # print(message['content'])
    # print("All extracted URLs from the message:")
    # print(urls)
    for url in urls:
        output = {}
        output['source'] = ailurlextract
        output['source-uuid'] = uuid
        output['default-encoding'] = 'UTF-8'

        output['meta'] = {}
        output['meta']['parent:discord:message_id'] = message['id']

        surl = url.split()[0]
        output['meta']['discord:url-extracted'] = surl
        u = urlparse(surl)

        if u.hostname is not None:
            if "discord.gg" in u.hostname:
                print("Found an invite link!")
                code = u.path.replace("/", "")
                joinServer(code)
                continue
            elif "discord.com" in u.hostname:
                continue

        # If the url is not valid, drop it and continue
        if not validators.url(surl):
            continue
        
        if args.verbose:
            print("Downloading and parsing {}".format(surl), file=sys.stderr)
        
        signal.alarm(10)
        try:
            article = newspaper.Article(surl)
        except TimeoutError:
            print("Timeout reached for {}".format(surl), file=sys.stderr)
            continue
        else:
            signal.alarm(0)

        # TODO: Check if the URL has already been analysed (caching)
        
        try:
            article.download()
            article.parse()
        except:
            if args.verbose:
                print("Unable to download/parse {}".format(surl), file=sys.stderr)
            continue

        #Encoding the URL of the message into base64
        content_bytes = article.html.encode('utf-8')
        output['data-sha256'] = hashlib.sha256(content_bytes).hexdigest()
        output['data'] = base64.b64encode(content_bytes).decode('utf-8')

        nlpFailed = False

        try:
            article.nlp()
        except:
            if args.verbose:
                print("Unable to nlp {}".format(surl), file=sys.stderr)
            nlpFailed = True

            # print("Extracting metadata instead.")
            output['meta']['embedded-objects'] = []
            for embedded in message['embeds']:
                e = {}
                fields = ['title', 'type', 'url', 'description', 'timestamp', 'footer', 'image', 'thumbnail', 'video', 'provider', 'author', 'fields']
                for field in fields:
                    if field in embedded:
                        e[field] = embedded[field]
                output['meta']['embedded-objects'].append(e)

            print("Found a link!")
            print("The JSON of the extracted URL is:")
            print(json.dumps(output, indent=4, sort_keys=True))
            
            # TODO: publish to AIL

            continue
    
        if nlpFailed:
            continue
        
        output['meta']['newspaper:text'] = article.text
        output['meta']['newspaper:authors'] = article.authors
        output['meta']['newspaper:keywords'] = article.keywords
        output['meta']['newspaper:publish_date'] = article.publish_date
        output['meta']['newspaper:top_image'] = article.top_image
        output['meta']['newspaper:movies'] = article.movies

        print("Found a link!")
        print("The JSON of the extracted URL is:")
        print(json.dumps(output, indent=4, sort_keys=True))
        # TODO: publish to AIL


def joinServer(code):
    server = client.getInfoFromInviteCode(code).json()['guild']
    print("Invite code: " + code)
    print("Trying to join the server " + server['name'] + " now...")
    server_id = server['id']
    if not server_id in scanned_servers:
        # The waiting time can be reduced, but the lower the time waited between joining servers, the higher the risk to get banned
        client.joinGuild(code, wait=10) # TODO: check if joining was successful
        print("Joined the server successfully!")
        print("Scanning the newly joined server...")
        scanServer(server)
        print("Scan successful!\n")
    else:
        print("Already in this server! Continuing scan...\n")


parser = argparse.ArgumentParser()
parser.add_argument("query", help="query to search on Discord to feed AIL")
parser.add_argument("--verbose", help="verbose output", action="store_true")
parser.add_argument("--nocache", help="disable cache", action="store_true")
parser.add_argument("--messagelimit", help="maximum number of message to fetch", type=int, default=50) # TODO: replace hardcoded value with variable
parser.add_argument("--replies", help="follow every message of a thread", action="store_true")
args = parser.parse_args()
scanned_servers = []

client.gateway.run(auto_reconnect=True)