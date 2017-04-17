#!/usr/bin/env python

import os
import sys
import argparse
import requests
import json
import magic

from ConfigParser import SafeConfigParser
from urlparse import urljoin
from vod_metadata import VodPackage


def read_config(config_file=None):
    # Read settings from config file
    # TODO: check availability of all needed settings
    config = {}
    if config_file:
        execfile(config_file, config)
    else:
        execfile(os.path.join(sys.path[0], 'config.py'), config)
    return config


def parse_args(argv=None):
    # Parse commandline options and parameters
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--auto', action='store_true',
                        help='Run non-interactively')
    parser.add_argument('--hd', action='store_true',
                        help='Treat asset as HD content if unknown')
    parser.add_argument('files', nargs='*', help='Filenames to be encoded')

    return parser.parse_args(argv)


def retrieve_vod_list(status=0, paging=True, limit=100):
    # Retrieve list of assets from TeleUP api vod endpoint
    api_endpoint = config['teleup_url']
    api_auth = (config['teleup_secret'], '')
    url = '%s?status=%s&limit=%s' % (api_endpoint, status, limit)

    sess = requests.Session()
    resp = sess.get(url, auth=(config['teleup_secret'], ''))
    if not resp.ok:
        print('Something went wrong with the TeleUP API: ' + resp.text)
        return False

    resp_json = resp.json()
    output = []
    output.extend(resp_json.get('data'))

    if paging:
        while 'next' in resp_json.get('paging', {}):
            resp = sess.get(
                urljoin(api_endpoint, resp_json['paging']['next']),
                auth=api_auth
            )
            resp_json = resp.json()
            output.extend(resp_json.get('data'))

    return output


def update_vod_status(vod_id, status, encode_job_id, msg=None):
    # Update encoding status of vod asset in TeleUP api
    api_endpoint = config['teleup_url']
    api_auth = (config['teleup_secret'], '')

    query = {
        'id': vod_id,
        'status': status,
        'encode_job_id': encode_job_id
    }

    if msg:
        query['observation'] = msg

    r = requests.patch(api_endpoint, data=query, auth=api_auth)

    return r


def output_job_definition(file_name, hd_content, action='AddMedia',
                          output='wowza_multibitrate_mp4',):
    # Output encoding job JSON
    job_spec = {
        'userid': config['encoding_user'],
        'userkey': config['encoding_secret'],
        'notify': config['notify']
    }

    job_spec['action'] = action
    job_spec['source'] = '%s/%s' % (config['source'], file_name)

    if output == 'wowza_multibitrate_mp4':
        job_format = {}
        job_format['output'] = output

        if hd_content:
            job_format['bitrates'] = config['bitrates']['hd']
            job_format['sizes'] = config['sizes']['hd']
        else:
            job_format['bitrates'] = config['bitrates']['sd']
            job_format['sizes'] = config['sizes']['sd']

        job_format['destination'] = '%s/%s.smil' % (
            config['destination'],
            os.path.splitext(file_name)[0]
        )

        job_spec['format'] = job_format

    elif output == 'simple':
        # separate files, probably replaced with wowza_multibitrate
        job_formats = []

        if hd_content:
            outputs = config['hd_outputs']
        else:
            outputs = config['sd_outputs']

        for output in outputs:
            destination = '%s%s_%s_%s.%s' % (
                config['destination'],
                os.path.splitext(file_name)[0],
                output['size'],
                output['bitrate'],
                output['output']
            )
            output.update({'destination': destination})
            job_formats.append(output)

        job_spec['format'] = job_formats

    return job_spec


if __name__ == "__main__":
    config = read_config()

    args = parse_args()

    if args.hd:
        hd_content = True
    else:
        hd_content = False

    # TODO: maybe call this `api` instead of `auto`
    # TODO: run this code when files have been added on the commandline
    if not args.auto:
        for input_file in args.files:
            if os.path.isfile(input_file):
                if 'xml' in magic.from_file(input_file).lower():
                    vod_package = VodPackage(input_file)
                    file_name = vod_package.D_content['movie']
                    hd_content = vod_package.D_app['movie']['HDContent'] == 'Y'
                elif 'mpeg' in magic.from_file(input_file).lower():
                    file_name = input_file
                else:
                    print('Not xml nor mpeg data, this might fail...')
                    file_name = input_file
            else:
                print('File does not exist (locally), this might fail...')
                file_name = input_file

            api_query = output_job_definition(input_file, hd_content)
            print(json.dumps({'query': api_query}, indent=4, sort_keys=True))

    else:
        assets = retrieve_vod_list(status=None, limit=3, paging=False)

        for asset in assets:
            file_name = asset['movie_file']
            hd_content = asset['movie_hd']
            api_query = output_job_definition(file_name, hd_content)

            print(json.dumps({'query': api_query}, indent=4, sort_keys=True))

            answer = raw_input('Want to continue? (n) ')
            if answer not in ('y', 'Y'):
                print('skipping...')
                continue

            payload = {'json': json.dumps({'query': api_query})}
            res = requests.post(config['encoding_url'], data=payload)
            res_json = json.dumps(res.json(), indent=4)

            if res.ok:
                if 'errors' in res.json()['response']:
                    print('API gives an error:\n%s' % (res_json))
                else:
                    print(res_json)
            else:
                print('An unknown problem occurred:\n%s' % (res.text))
