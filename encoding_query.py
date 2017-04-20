#!/usr/bin/env python

import os
import sys
import argparse
import requests
import json
import magic

from urlparse import urljoin
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
        execfile(config_file, config)
    else:
        execfile(os.path.join(sys.path[0], 'config.py'), config)

    mandatory_keys = [
        'teleup_url',
        'teleup_secret',
        'encoding_url',
        'encoding_user',
        'encoding_secret',
        'source',
        'destination',
        'notify',
        'sizes',
        'bitrates'
    ]

    missing_keys = set(mandatory_keys).difference(config.keys())
    if missing_keys:
        print('Missing these settings in config file:\n%s' %
              '\n'.join(missing_keys))
        sys.exit()

    return config


def parse_args(argv=None):
    """Return args object

    Parsed from commandline options and arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--auto', action='store_true',
                        help='Run non-interactively')
    parser.add_argument('--update_status', action='store_true',
                        help='Only update status of running jobs')
    parser.add_argument('--hd', action='store_true',
                        help='Treat asset as HD content if unknown')
    parser.add_argument('files', nargs='*', help='Filenames to be encoded')

    return parser.parse_args(argv)


def get_vod_list(status=VOD_TODO, paging=True, limit=100):
    """Return list of assets from TeleUP api vod endpoint"""
    api_endpoint = config['teleup_url']
    api_auth = (config['teleup_secret'], '')
    url = '%s?status=%s&limit=%s' % (api_endpoint, status, limit)

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
                urljoin(api_endpoint, resp_json['paging']['next']),
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

    payload = json.dumps([query])
    # TODO: test for success
    resp = requests.patch(api_endpoint, json=[query], auth=api_auth)

    return resp.ok


def job_definition(file_name, hd_content, action='AddMedia',
                   output='wowza_multibitrate_mp4',):
    """Return encoding job dict

    To be converted to json before sending to API
    """
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

    return_vals = ('id', 'created', 'started', 'progress', 'status')
    data = resp.json()['response']
    return {k: data.get(k, None) for k in return_vals}


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
            print('API returned an error:\n%s' % (resp_json))
            return False
        else:
            print(resp_json)
            return resp_json['response']['MediaID']
    else:
        print('An unknown problem occurred:\n%s' % (resp.text))
        return False


if __name__ == "__main__":
    config = read_config()

    args = parse_args()

    if args.hd:
        hd_content = True
    else:
        hd_content = False

    # TODO: maybe call this `api` instead of `auto`
    # TODO: run this code when files have been added on the commandline
    # TODO: maybe use basename on filenames
    # NOTE: do we actually want to run this on individual files?
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

            job_def = job_definition(file_name, hd_content)

            print(json.dumps({'query': job_def}, indent=4, sort_keys=True))

            answer = raw_input('Want to continue? (n) ')
            if answer not in ('y', 'Y'):
                print('skipping...')
                continue

            send_job(job_def)

    else:
        """
        Step 1: retrieve vod_list of running job assets
        Step 2: check encoding status of all jobs
        Step 3: update vod asset encoding status
        Step 4: retrieve vod_list of to_encode assets
        Step 5: create and send jobs to encoding.com
        Step 6: update vod status encoding status

        """

        # Step 1, 2 and 3
        active_assets = get_vod_list(status=VOD_ACTIVE)
        for asset in active_assets:
            if not asset.get('encode_job_id'):
                # TODO: log error
                print('No encode_job_id, cannot check job status')
                continue

            status = get_job_status(asset.get('encode_job_id'))

            if status['status'] in JOB_ACTIVE:
                observation = '%s %s%%' % (status['status'],
                                           status['progress'])
                update_vod_status(asset['id'], VOD_ACTIVE, msg=observation)
                if args.update_status:
                    print('%s: %s' % (asset['id'], observation))
            elif status['status'] in JOB_SUCCESS:
                update_vod_status(asset['id'], VOD_SUCCESS, msg='-')
                if args.update_status:
                    print('%s: %s' % (asset['id'], 'done'))
            elif status['status'] in JOB_FAIL:
                update_vod_status(asset['id'], VOD_FAIL, msg=status['status'])
                if args.update_status:
                    print('%s: %s' % (asset['id'], 'failed'))
            else:
                print('Encoding status %s unknown' % (status['status']))

        if args.update_status:
            print('Only checking status, skipping adding new jobs')
            sys.exit()

        # Step 4, 5 and 6
        to_encode_assets = get_vod_list(status=VOD_TODO)
        for asset in to_encode_assets:
            file_name = asset['movie_file']
            hd_content = asset['movie_hd']
            job_def = job_definition(file_name, hd_content)

            # TODO: save this for debug
            print(json.dumps({'query': job_def}, indent=4, sort_keys=True))

            answer = raw_input('Want to continue? (n) ')
            if answer not in ('y', 'Y'):
                print('skipping...')
                continue

            job_id = send_job(job_def)

            if job_id:
                update_vod_status(asset['id'], VOD_ACTIVE, job_id)
            else:
                print('Failure encoding asset %s' % (asset['id']))
