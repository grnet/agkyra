from ws4py.websocket import WebSocket


class WebSocketProtocol(WebSocket):
    """Helper-side WebSocket protocol for communication with GUI:

    -- INTERRNAL HANDSAKE --
    GUI: {"token": <token>}
    HELPER: {"ACCEPTED": 202}" or "{"ERROR": 401, "MESSAGE": <message>}

    -- GET SETTINGS --
    GUI: {"method": "get", "path": "settings"}
    HELPER:
        {
            "token": <user token>,
            "url": <auth url>,
            "container": <container>,
            "directory": <local directory>,
            "exclude": <file path>
        } or {"ERROR": <error code>, "MESSAGE": <message>}"

    -- PUT SETTINGS --
    GUI: {
            "method": "put", "path": "settings",
            "token": <user token>,
            "url": <auth url>,
            "container": <container>,
            "directory": <local directory>,
            "exclude": <file path>
        }
    HELPER: {"CREATED": 201} or {"ERROR": <error code>, "MESSAGE": <message>}

    -- GET STATUS --
    GUI: {"method": "get", "path": "status"}
    HELPER: ""progres": <int>, "paused": <boolean>} or
        {"ERROR": <error code>, "MESSAGE": <message>}
    """

    def __init__(self, *args, **kwargs):
        super(WebSocketProtocol, self).__init__(*args, **kwargs)
        print 'lala'
