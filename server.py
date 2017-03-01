# -*- coding: utf-8 -*-


import os
import sys
import time
import datetime
from flask import Flask
from flask import jsonify
from flask import request
from flask import redirect
from flask import send_from_directory
from flask_sockets import Sockets
import jinja2
from api_exception import InvalidUsage
from hpOneView.oneview_client import OneViewClient
from hpOneView.exceptions import HPOneViewException
import json


class Reservation(object):
    def __init__(self):
        self.file = 'reservation.json'
        self.data = None

        # read json file
        try:
            with open(self.file, 'r') as json_data:
                self.data = json.load(json_data)
                json_data.close()
        except IOError:
            self.data = {}
            self.save()

    def save(self):
        with open(self.file, 'w') as json_data:
            json_data.write(json.dumps(self.data))
            json_data.close()

    def reserve(self, uuid, owner):
        self.data.update({uuid: owner})
        self.save()

    def get(self, uuid):
        try:
            return self.data[uuid]
        except KeyError:
            return ""

    def release(self, uuid):
        try:
            del self.data[uuid]
            self.save()
        except KeyError:
            pass

app = Flask(__name__)
sockets = Sockets(app)

try:
    login = os.environ["OVLOGIN"]
    password = os.environ["OVPASSWD"]
except KeyError:
    print("Please set OVLOGIN and OVPASSWD environment variable")
    sys.exit(1)


config = {
    "ip": "10.3.87.10",
    "credentials": {
        "userName": login,
        "password": password
    }
}


# Initialize oneview client
oneview_client = OneViewClient(config)

# Initialize reservation
resa = Reservation()


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


@sockets.route('/reserve')
def reserve(ws):
    data = json.loads(ws.receive())
    resa.reserve(data["uuid"], data["owner"])
    ws.send(data["uuid"])


@sockets.route('/release')
def release(ws):
    data = json.loads(ws.receive())
    resa.release(data["uuid"])
    ws.send(data["uuid"])


@sockets.route('/deploy')
def deploy(ws):
    data = json.loads(ws.receive())
    server = oneview_client.server_hardware.get(data['uuid'])
    profile = oneview_client.server_profiles.get(server['serverProfileUri'])
    macaddress = get_mac(profile)
    flagpath = 'flags/' + macaddress
    if os.path.exists(flagpath):
        os.remove(flagpath)
    # Power off server
    try:
        configuration = {
            "powerState": "Off",
            "powerControl": "MomentaryPress"
        }
        server_power = oneview_client.server_hardware.update_power_state(
                configuration,
                data["uuid"])
    except HPOneViewException as e:
        print(e.msg)

    msg = data["uuid"] + "requested to stop."
    ws.send(msg)
    time.sleep(10)
    # Power off server
    try:
        configuration = {
            "powerState": "On",
            "powerControl": "MomentaryPress"
        }
        server_power = oneview_client.server_hardware.update_power_state(
                configuration,
                data["uuid"])
    except HPOneViewException as e:
        print(e.msg)
    msg = data["uuid"] + "powered on."
    ws.send(msg)


@sockets.route('/status')
def status(ws):
    while not ws.closed:
        server_hardware_all = oneview_client.server_hardware.get_all()
        for server in server_hardware_all:
            if server['serverProfileUri'] is not None:
                profile = oneview_client.server_profiles.get(
                        server['serverProfileUri'])
                if 'iPXE' in profile["name"]:
                    data = define_status(server, profile)
                    ws.send(json.dumps(data))
        time.sleep(5)


@app.route('/')
@app.route('/available')
def available():
    # Get hardware
    server_hardware_all = oneview_client.server_hardware.get_all()
    html = render_template("available.html", server_hardware_all)
    return html


@app.route('/ready2deploy')
def ready2deploy():
    # Get hardware
    server_hardware_all = oneview_client.server_hardware.get_all()

    # Craft required data
    data2print = []
    for server in server_hardware_all:
        if server['serverProfileUri'] is not None:
            profile = oneview_client.server_profiles.get(
                    server['serverProfileUri'])
            if 'iPXE' in profile["name"]:
                macaddress = get_mac(profile)
                data2print.append({
                    'shortModel': server['shortModel'],
                    'name': server['name'],
                    'uuid': server['uuid'],
                    'macaddress': macaddress,
                    'powerState': server['powerState'],
                    'owner': resa.get(server['uuid'])
                    })
    html = render_template("ready2deploy.html", data2print)
    return html


@app.route('/deployed')
def deployed():
    # Get hardware
    server_hardware_all = oneview_client.server_hardware.get_all()
    html = render_template("deployed.html", server_hardware_all)
    return html


@app.route('/config/<ip>')
def configure(ip):
    # Not really great code...
    global config
    global oneview_client
    global server_hardware_all
    config["ip"] = ip
    oneview_client = OneViewClient(config)
    server_hardware_all = oneview_client.server_hardware.get_all()
    return redirect("available")


@app.route('/css/<path>')
def send_css(path):
    return send_from_directory('templates/css', path)


@app.route('/img/<path>')
def send_img(path):
    return send_from_directory('templates/img', path)


@app.route('/boot')
def boot():
    macs = os.listdir("flags")
    macs.remove('README.md')
    script = render_template("boot.template", macs)
    return script


@app.route('/bootipxe/<macaddress>/<manufacturer>')
def bootipxe(macaddress, manufacturer):
    # Write a trace file

    filename = "flags/" + macaddress
    with open(filename, 'w') as tracefile:
        tracefile.write(manufacturer)
        tracefile.close()
    script = render_template("bootipxe.template")
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
        tracefile.write('deployed')
        tracefile.close()
        data = {"status": "ok"}
        resp = jsonify(data)
        resp.status_code = 200
        return resp


@app.route('/deploy/os', methods=["POST"])
def deploy_osready():
    # Write a trace file
    try:
        macaddress = request.json['macaddress']
    except KeyError:
        raise InvalidUsage(
                'Invalid key provided should be macaddress', status_code=400)

    filename = "flags/" + macaddress
    with open(filename, 'w') as tracefile:
        tracefile.write('osready')
        tracefile.close()
        data = {"status": "ok"}
        resp = jsonify(data)
        resp.status_code = 200
        return resp


def render_template(template, values=None):
    # Initialize Template system (jinja2)
    templates_path = 'templates'
    jinja2_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates_path))
    try:
        template = jinja2_env.get_template(template)
    except jinja2.exceptions.TemplateNotFound as e:
        print('Template "{}" not found in {}.'
              .format(e.message, jinja2_env.loader.searchpath[0]))

    if values is None:
        data = template.render()
    else:
        data = template.render(r=values)

    return data


def define_status(server, profile):
    flag = None
    content = None
    deployed = None
    osready = None
    status = ''
    macaddress = get_mac(profile)
    flagpath = 'flags/' + macaddress
    if os.path.exists(flagpath):
        flag = True
        # Checking inside flag
        with open(flagpath, 'r') as trace:
            content = trace.read()
            if 'deployed' in content:
                deployed = True
            if 'osready' in content:
                osready = True

    if (server["powerState"] == 'On' and deployed is True):
        status = 'OS deployed, rebooting'
    elif (server["powerState"] == 'On' and osready is True):
        status = 'System ready'
    elif (server["powerState"] == 'On' and flag is True):
        status = 'Deployment in progress'
    elif (server["powerState"] == 'On'):
        status = 'PowerOn'
    elif (server["powerState"] == 'Off'):
        status = 'PowerOff'
    data = {"uuid": server["uuid"],
            "status": status,
            "timestamp": datetime.datetime.now().isoformat()}
    return data


def get_mac(profile):
    macaddress = profile['connections'][0]['mac'].lower()
    macaddress = macaddress.replace(':', '')
    return macaddress


if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    server = pywsgi.WSGIServer(('', 5000), app, handler_class=WebSocketHandler)
    server.serve_forever()
