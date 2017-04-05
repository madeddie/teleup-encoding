#!/usr/bin/env python

import os
import sys
import requests
import json
import magic

from ConfigParser import SafeConfigParser
from vod_metadata import VodPackage


def read_config(config_file='config.py'):
    # TODO: check availability of all needed settings
    config = {}
    execfile(config_file, config)
    return config


if __name__ == "__main__":
    config = read_config()
    query = {
        'userid': config['userid'],
        'userkey': config['userkey'],
        'notify': config['notify']
    }

    query['action'] = 'AddMedia'

    # TODO: proper optparsing
    if sys.argv[1] < 1:
        print("Please provide name of file to process.")
        sys.exit()
    else:
        input_file = sys.argv[1]

    hdcontent = False

    if os.path.isfile(input_file):
        if 'xml' in magic.from_file(input_file).lower():
            vod_package = VodPackage(input_file)
            file_name = vod_package.D_content['movie']
            hdcontent = vod_package.D_app['movie']['HDContent'] == 'Y'
        elif 'mpeg' in magic.from_file(input_file).lower():
            file_name = input_file
        else:
            print('Not xml nor mpeg data, this might fail...')
            file_name = input_file
    else:
        print('File does not exist (locally), this might fail...')
        file_name = input_file

    query['source'] = config['source'] + file_name

    formats = []
    if hdcontent:
        outputs = config['hd_outputs']
    else:
        outputs = config['sd_outputs']

    for output in outputs:
        destination = '%s%s_%s.%s' % (
            config['destination'],
            os.path.splitext(file_name)[0],
            output['size'],
            output['output']
        )
        output.update({'destination': destination})
        formats.append(output)

    query['format'] = formats

    print(json.dumps({'query': query}, indent=4, sort_keys=True))
    answer = raw_input('Want to continue? (n) ')
    if answer not in ('y', 'Y'):
        print('stopping...')
        sys.exit()

    payload = {'json': json.dumps({'query': query})}
    res = requests.post(config['api_url'], data=payload)

    if res.ok:
        if 'errors' in res.json()['response']:
            print('API gives an error:\n' + json.dumps(res.json(), indent=4))
        else:
            print(json.dumps(res.json(), indent=4))
    else:
        print('An unknown problem occurred:\n' + res.text)
