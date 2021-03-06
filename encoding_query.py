#!/usr/bin/env python

import argparse
import json
import logging
import os
import sys
from ftplib import FTP
try:
    from urlparse import urlsplit, urljoin
except ImportError:
    from urllib.parse import urlsplit, urljoin

import requests
from vod_metadata import VodPackage

# TeleUP status constants
VOD_STATUS = {
    'TODO': 0,     # selected to be encoded
    'ACTIVE': 1,   # encoding started
    'SUCCESS': 5,  # encoded with success (ready to rent)
    'FAIL': -1,    # encoding failed
    'REJECT': -5,  # rejected (will not be processed)
}

# Encoding.com status constants
JOB_ACTIVE = ('New', 'Downloading', 'Waiting for encoder',
              'Processing', 'Saving')
JOB_SUCCESS = ('Finished')
JOB_FAIL = ('Error')


def read_config(config_file=None):
    """Return config dict with values from config file"""
    config = {}
    if not config_file:
        config_file = os.path.join(sys.path[0], 'config.py')
    try:
        exec(open(config_file).read(), config)
    except IOError:
        logging.error("Can't find file {}, exiting".format(config_file))
        sys.exit()

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
        logging.error('Missing config setting(s) {}'.format(','.join(missing)))
        sys.exit()

    return config


def parse_args(argv=None):
    """Return args object

    Parsed from commandline options and arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--config_file',
                        help='Give full location of config file to use')
    parser.add_argument('--update_status', action='store_true',
                        help='Only update status of running jobs')
    parser.add_argument('--cleanup', action='store_true',
                        help='Delete files for encoded and/or rejected assets')
    parser.add_argument('--dry_run', action='store_true',
                        help="Dry run; don't make any actual changes")
    parser.add_argument('--loglevel', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING',
                                 'ERROR', 'CRITICAL'],
                        help='Set log level')

    return parser.parse_args(argv)


def get_vod_list(status=VOD_STATUS['TODO'], paging=True, limit=100):
    """Return list of assets from TeleUP api vod endpoint"""
    api_endpoint = config['teleup_url']
    api_auth = (config['teleup_secret'], '')
    payload = {'status': status, 'limit': limit}

    sess = requests.Session()
    resp = sess.get(api_endpoint, auth=api_auth, params=payload)
    if not resp.ok:
        logging.warning(
            'Something went wrong with the TeleUP API: {}'.format(resp.text)
        )
        return False

    resp_json = resp.json()
    output = []
    output.extend(resp_json.get('data'))

    if paging:
        while 'next' in resp_json.get('paging', {}):
            url = urljoin(api_endpoint, resp_json['paging']['next'])
            resp = sess.get(url, auth=api_auth)
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

    resp = requests.patch(api_endpoint, json=[query], auth=api_auth)
    if not resp.ok:
        logging.warning('Updating vod status failed (id: {})'.format(vod_id))

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
    resp = requests.post(api_endpoint, data=payload)

    if not resp.ok:
        logging.warning(
            'Retrieving encoding job status failed (id: {})'.format(job_id)
        )
        return False

    data = resp.json()['response']

    if data.get('errors'):
        logging.warning(
            'Retrieving encoding job status failed (id: {})\n{}'.format(
                job_id, data['errors']['error']
            )
        )
        return False

    return_vals = ('id', 'created', 'started', 'progress', 'status',
                   'description')
    return {x: data.get(x) for x in return_vals}


def send_job(job_def):
    """Send job JSON to encoding API to be processed"""
    api_endpoint = config['encoding_url']

    payload = {'json': json.dumps({'query': job_def})}
    resp = requests.post(api_endpoint, data=payload)
    if not resp.ok:
        logging.warning(
            'Failed sending encoding job (src: {})'.format(job_def['source'])
        )
        return False
    resp_json = resp.json()

    if resp.ok:
        if 'errors' in resp_json['response']:
            logging.warning('API returned an error:\n{}'.format(resp_json))
            return False
        else:
            logging.info(resp_json)
            return resp_json['response']['MediaID']
    else:
        logging.warning('An unknown problem occurred:\n{}'.format(resp.text))
        return False


def clean_files(status, force=False):
    """Clean up files on TeleUP server

    Delete files for assets with given status; i.e. SUCCESS or REJECT
    """
    allowed = (VOD_STATUS['SUCCESS'], VOD_STATUS['REJECT'])
    if status not in allowed and not force:
        msg = (
            'When trying to delete files for assets _not_ marked with '
            "SUCCESS or REJECT, please use 'force=True'"
        )
        logging.warning(msg)
        return False

    ftp_info = urlsplit(config['source'])
    conn = FTP(ftp_info.hostname, ftp_info.username, ftp_info.password)
    if ftp_info.path:
        conn.cwd(ftp_info.path.lstrip('/'))
    ftpfiles = conn.nlst()

    matching = []
    for asset in get_vod_list(status=status):
        asset_base = '_'.join(asset['movie_file'].split('_')[0:2])
        matching.extend(
            [s for s in ftpfiles if asset_base in s]
        )

    for f in matching:
        logging.info('deleting: ' + f)
        conn.delete(f)

    conn.close()


if __name__ == "__main__":
    args = parse_args()
    config = read_config(args.config_file)

    loglevel = getattr(logging, args.loglevel)
    if args.dry_run:
        print('Not making any actual changes, setting loglevel to DEBUG')
        loglevel = getattr(logging, 'DEBUG')

    log_file = os.path.join(sys.path[0], 'encoding.log')
    logging.basicConfig(
        format='%(asctime)s %(message)s',
        level=loglevel,
        filename=log_file
    )
    if os.isatty(sys.stdout.fileno()):
        logging.getLogger().addHandler(logging.StreamHandler())

    # If cleaning up, only cleanup and exit
    if args.cleanup and not args.dry_run:
        for status in ('REJECT', 'SUCCESS'):
            logging.info('cleaning files for assets marked: {}'.format(status))
            clean_files(status=VOD_STATUS[status])

        sys.exit()

    # Check active jobs and update vod status
    active_assets = get_vod_list(status=VOD_STATUS['ACTIVE'])
    if not active_assets:
        logging.info('No active jobs')
    for asset in active_assets:
        if not asset.get('encode_job_id'):
            logging.warning('No encode_job_id, cannot check job status')
            continue

        status = get_job_status(asset.get('encode_job_id'))

        if not status:
            observation = 'failed to retrieve status for {}'.format(
                asset.get('encode_job_id')
            )
            vod_status = VOD_STATUS['FAIL']
        elif status['status'] in JOB_ACTIVE:
            observation = '{} {}%'.format(status['status'], status['progress'])
            vod_status = VOD_STATUS['ACTIVE']
            logging.info('{}: {}'.format(asset['id'], observation))
        elif status['status'] in JOB_SUCCESS:
            observation = '-'
            vod_status = VOD_STATUS['SUCCESS']
            logging.info('{}: {}'.format(asset['id'], 'done'))
        elif status['status'] in JOB_FAIL:
            if status.get('description'):
                observation = status['description']
            else:
                observation = status['status']
            vod_status = VOD_STATUS['FAIL']
            logging.info('{}: {}'.format(asset['id'], 'failed'))
        else:
            observation = 'Encoding status {} unknown'.format(status['status'])
            vod_status = VOD_STATUS['FAIL']
            logging.info('{}: {}'.format(asset['id'], observation))

        if not args.dry_run:
            update_vod_status(asset['id'], vod_status, msg=observation)

    if args.update_status:
        logging.info('Only updating active status, skipping adding new jobs')
        sys.exit()

    # Run encoding jobs for selected vod assets
    to_encode_assets = get_vod_list(status=VOD_STATUS['TODO'])
    if not to_encode_assets:
        logging.debug('No new assets to encode')
    for asset in to_encode_assets:
        file_name = asset['movie_file']
        hd_content = asset.get('movie_hd', False)
        job_def = job_definition(file_name, hd_content)

        logging.info(json.dumps({'query': job_def}, indent=4, sort_keys=True))

        if not args.dry_run:
            job_id = send_job(job_def)

            if job_id:
                update_vod_status(asset['id'], VOD_STATUS['ACTIVE'], job_id)
            else:
                logging.warning(
                    'Failure encoding asset (id: {})'.format(asset['id'])
                )

    # If we got this far, notify our healthchecks.io endpoint
    if not args.dry_run and config.get('healthcheck_url'):
        requests.get(config['healthcheck_url'])
