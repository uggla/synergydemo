# -*- coding: utf-8 -*-


from flask import Flask
from flask import jsonify
from flask import request
from flask_sockets import Sockets
import jinja2
import time
from api_exception import InvalidUsage


app = Flask(__name__)
sockets = Sockets(app)


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


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
    html = render_template("main.template")
    return html


@app.route('/boot')
def boot():
    script = render_template("boot.template")
    return script


@app.route('/deploy/complete', methods=["POST"])
def deploy_complete():
    # Write a trace file
    try:
        macaddress = request.json['macaddress']
    except KeyError:
        raise InvalidUsage(
                'Invalid key provided should be macaddress', status_code=400)

    filename = "flags/" + macaddress
    with open(filename, 'w') as tracefile:
        tracefile.close()
        data = {"status": "ok"}
        resp = jsonify(data)
        resp.status_code = 200
        return resp


def render_template(template):
    # Initialize Template system (jinja2)
    templates_path = 'templates'
    jinja2_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates_path))
    try:
        template = jinja2_env.get_template(template)
    except jinja2.exceptions.TemplateNotFound as e:
        print('Template "{}" not found in {}.'
              .format(e.message, jinja2_env.loader.searchpath[0]))

    data = template.render()
    return data

if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    server = pywsgi.WSGIServer(('', 5000), app, handler_class=WebSocketHandler)
    server.serve_forever()
