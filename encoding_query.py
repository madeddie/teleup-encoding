#!/usr/bin/env python

import argparse
import json
import os
import sys
try:
    from urlparse import urljoin
except ImportError:
    from urllib.parse import urljoin

import requests
from vod_metadata import VodPackage

# TeleUP status constants
VOD_TODO = 0     # selected to be encoded
VOD_ACTIVE = 1   # encoding started
VOD_SUCCESS = 5  # encoded with success (ready to rent)
VOD_FAIL = -1    # encoding failed
VOD_REJECT = -5  # rejected (will not be processed)

# Encoding.com status constants
JOB_ACTIVE = ('New', 'Downloading', 'Waiting for encoder',
              'Processing', 'Saving')
JOB_SUCCESS = ('Finished')
JOB_FAIL = ('Error')


def read_config(config_file=None):
    """Return config dict with values from config file"""
    config = {}
    if config_file:
        exec(open(config_file).read(), config)
    else:
        exec(open(os.path.join(sys.path[0], 'config.py')).read(), config)

    mandatory = [
        'teleup_url',
        'teleup_secret',
        'encoding_url',
        'encoding_user',
        'encoding_secret',
        'source',
        'destination',
        'sizes',
        'bitrates'
    ]

    missing = set(mandatory).difference(list(config.keys()))
    if missing:
        print('Missing settings in config:\n{}'.format('\n'.join(missing)))
        sys.exit()

    return config


def parse_args(argv=None):
    """Return args object

    Parsed from commandline options and arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--update_status', action='store_true',
                        help='Only update status of running jobs')

    return parser.parse_args(argv)


def get_vod_list(status=VOD_TODO, paging=True, limit=100):
    """Return list of assets from TeleUP api vod endpoint"""
    api_endpoint = config['teleup_url']
    api_auth = (config['teleup_secret'], '')
    url = '{}?status={}&limit={}'.format(api_endpoint, status, limit)

    sess = requests.Session()
    resp = sess.get(url, auth=(config['teleup_secret'], ''))
    if not resp.ok:
        # TODO: print nothing except when asked for debugging
        # TODO: log errors
        print('Something went wrong with the TeleUP API: ' + resp.text)
        return False

    resp_json = resp.json()
    output = []
    output.extend(resp_json.get('data'))

    if paging:
        while 'next' in resp_json.get('paging', {}):
            resp = sess.get(
                urlparse.urljoin(api_endpoint, resp_json['paging']['next']),
                auth=api_auth
            )
            resp_json = resp.json()
            output.extend(resp_json.get('data'))

    return output


def update_vod_status(vod_id, status, encode_job_id=None, msg=None):
    """Update encoding status of vod asset in TeleUP api"""
    api_endpoint = config['teleup_url']
    api_auth = (config['teleup_secret'], '')

    query = {
        'id': vod_id,
        'status': status
    }

    if encode_job_id:
        query['encode_job_id'] = encode_job_id
    if msg:
        query['observation'] = msg

    # TODO: test for success
    resp = requests.patch(api_endpoint, json=[query], auth=api_auth)

    return resp.ok


def job_definition(file_name, hd_content, action='AddMedia'):
    """Return encoding job dict

    To be converted to json before sending to API
    """
    job_spec = {
        'userid': config['encoding_user'],
        'userkey': config['encoding_secret']
    }

    if config.get('notify'):
        job_spec['notify'] = config['notify']

    job_spec['action'] = action
    job_spec['source'] = '{}/{}'.format(config['source'], file_name)

    job_format = {}
    job_format['output'] = 'wowza_multibitrate_mp4'

    if hd_content:
        job_format['bitrates'] = config['bitrates']['hd']
        job_format['sizes'] = config['sizes']['hd']
    else:
        job_format['bitrates'] = config['bitrates']['sd']
        job_format['sizes'] = config['sizes']['sd']

    job_format['destination'] = '{}/{}.smil'.format(
        config['destination'],
        os.path.splitext(file_name)[0]
    )

    job_spec['format'] = job_format

    return job_spec


def get_job_status(job_id):
    """Return status of encoding job

    Returns media id,
    created timestamp and started timestamp,
    status string and progress percentage
    """
    api_endpoint = config['encoding_url']

    query = {
        'userid': config['encoding_user'],
        'userkey': config['encoding_secret'],
        'action': 'GetStatus',
        'mediaid': job_id
    }

    payload = {'json': json.dumps({'query': query})}
    # TODO: check success
    resp = requests.post(api_endpoint, data=payload)
    data = resp.json()['response']

    return_vals = ('id', 'created', 'started', 'progress', 'status')
    return {x: data.get(x) for x in return_vals}


def send_job(job_def):
    """Send job JSON to encoding API to be processed"""
    api_endpoint = config['encoding_url']

    payload = {'json': json.dumps({'query': job_def})}
    # TODO check success
    resp = requests.post(api_endpoint, data=payload)
    resp_json = resp.json()

    # TODO: print nothing except when asked for debugging
    # TODO: log errors
    if resp.ok:
        if 'errors' in resp_json['response']:
            print('API returned an error:\n{}'.format(resp_json))
            return False
        else:
            print(resp_json)
            return resp_json['response']['MediaID']
    else:
        print('An unknown problem occurred:\n{}'.format(resp.text))
        return False


if __name__ == "__main__":
    config = read_config()

    args = parse_args()

    # Check active jobs and update vod status
    active_assets = get_vod_list(status=VOD_ACTIVE)
    for asset in active_assets:
        if not asset.get('encode_job_id'):
            # TODO: log error
            print('No encode_job_id, cannot check job status')
            continue

        status = get_job_status(asset.get('encode_job_id'))

        if status['status'] in JOB_ACTIVE:
            observation = '{} {}%'.format(status['status'], status['progress'])
            update_vod_status(asset['id'], VOD_ACTIVE, msg=observation)
            if args.update_status:
                print('{}: {}'.format(asset['id'], observation))
        elif status['status'] in JOB_SUCCESS:
            update_vod_status(asset['id'], VOD_SUCCESS, msg='-')
            if args.update_status:
                print('{}: {}'.format(asset['id'], 'done'))
        elif status['status'] in JOB_FAIL:
            update_vod_status(asset['id'], VOD_FAIL, msg=status['status'])
            if args.update_status:
                print('{}: {}'.format(asset['id'], 'failed'))
        else:
            print('Encoding status {} unknown'.format(status['status']))

    if args.update_status:
        print('Only checking status, skipping adding new jobs')
        sys.exit()

    # Run encoding jobs for selected vod assets
    to_encode_assets = get_vod_list(status=VOD_TODO)
    for asset in to_encode_assets:
        file_name = asset['movie_file']
        hd_content = asset.get('movie_hd', False)
        job_def = job_definition(file_name, hd_content)

        # TODO: save this for debug
        print(json.dumps({'query': job_def}, indent=4, sort_keys=True))

        try:
            answer = raw_input('Want to continue? (n) ')
        except NameError:
            answer = input('Want to continue? (n) ')
        if answer not in ('y', 'Y'):
            print('skipping...')
            continue

        job_id = send_job(job_def)

        if job_id:
            update_vod_status(asset['id'], VOD_ACTIVE, job_id)
        else:
            print('Failure encoding asset {}'.format(asset['id']))
