from flask import Flask
from flask import jsonify
from flask import request
from flask_sockets import Sockets
import time


app = Flask(__name__)
sockets = Sockets(app)


@sockets.route('/echo')
def echo_socket(ws):
    while not ws.closed:
        message = ws.receive()
        ws.send(message)
        for i in range(5):
            time.sleep(1)
            ws.send(message)


@sockets.route('/bla')
def bla_socket(ws):
    while not ws.closed:
        message = ws.receive()
        ws.send(message + 'blabla')
        for i in range(5):
            time.sleep(1)
            ws.send(message + 'blabla')


@app.route('/')
def hello():
    return 'Hello World!'


@app.route('/deploy/complete', methods=["POST"])
def deploy_complete():
    # Write a trace file
    macaddress = request.json['macaddress']
    with open(macaddress, 'w') as tracefile:
        tracefile.close()
        data = {"status": "ok"}
        resp = jsonify(data)
        resp.status_code = 200
        return resp


if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    server = pywsgi.WSGIServer(('', 5000), app, handler_class=WebSocketHandler)
    server.serve_forever()
