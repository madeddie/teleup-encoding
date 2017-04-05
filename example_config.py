api_url = 'https://manage.encoding.com/'
userid = ENCODING_API_ID
userkey = ENCODING_API_KEY
source = SOURCE_URL
destination = DESTINATION_URL
notify = NOTIFICATION_URL

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
