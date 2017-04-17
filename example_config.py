teleup_url = TELEUP_API_URL
teleup_secret = TELEUP_API_KEY

encoding_url = ENCODING_API_URL
encoding_user = ENCODING_API_USERID
encoding_secret = ENCODING_API_USERKEY

source = SOURCE_URL
destination = DESTINATION_URL
notify = NOTIFICATION_URL_OR_MAIL_ADDRESS

# New form, used for multibitrate
sizes = {
    'sd': '0x240,0x360,0x480',
    'hd': '0x288,0x360,0x720'
}

bitrates = {
    'sd': '400k,700k,1000k,1500k',
    'hd': '700k,1000k,2000k,3500k'
}

# Old form, deprecated
sd_outputs = [
    {
        'output': 'mp4',
        'size': '0x480',
        'bitrate': '1500k'
    },
    {
        'output': 'mp4',
        'size': '0x480',
        'bitrate': '1000k'
    },
    {
        'output': 'mp4',
        'size': '0x360',
        'bitrate': '700k'
    },
    {
        'output': 'mp4',
        'size': '0x240',
        'bitrate': '400k'
    }
]

hd_outputs = [
    {
        'output': 'mp4',
        'size': '0x720',
        'bitrate': '3500k'
    },
    {
        'output': 'mp4',
        'size': '0x720',
        'bitrate': '2000k'
    },
    {
        'output': 'mp4',
        'size': '0x360',
        'bitrate': '1000k'
    },
    {
        'output': 'mp4',
        'size': '0x288',
        'bitrate': '700k'
    }
]
