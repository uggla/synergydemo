# -*- coding: utf-8 -*-


import os
import sys
import time
import datetime
import docker
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
import uuid


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
    "ip": "10.6.25.10",
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


@app.route('/addprofile/<uuid>/<synergytype>')
def addprofile_route(uuid, synergytype):
    data = {'uuid': uuid,
            'type': synergytype}
    powering(data, 'Off')
    applying_profile(data)
    data = {"status": "ok"}
    resp = jsonify(data)
    resp.status_code = 200
    return resp


@sockets.route('/addprofile')
def addprofile_ws(ws):
    data = json.loads(ws.receive())
    ws.send(data["uuid"] + ' sending power off.')
    powering(data, 'Off')
    ws.send(data["uuid"] + ' applying profile...')
    applying_profile(data)


def powering(data, state):
    state = state.title()
    # Power off server
    try:
        configuration = {
            "powerState": state,
            "powerControl": "MomentaryPress"
        }
        oneview_client.server_hardware.update_power_state(
            configuration,
            data["uuid"])
    except HPOneViewException as e:
        print(e.msg)


def applying_profile(data):
    server = oneview_client.server_hardware.get(data['uuid'])
    templatename = 'Boot iPXE SY' + data['type']
    template = oneview_client.server_profile_templates.get_by_name(
            templatename)
    # Get new profile
    profile = oneview_client.server_profile_templates.get_new_profile(
        template['uri'])

    name = 'iPXE-' + str(uuid.uuid4()).split('-')[-1]
    profile['name'] = name
    profile['serverHardwareUri'] = server['uri']
    try:
        # Create a server profile
        oneview_client.server_profiles.create(profile, 10)
    except HPOneViewException as e:
        print(e.msg)


@sockets.route('/reserve')
def reserve_ws(ws):
    data = json.loads(ws.receive())
    resa.reserve(data["uuid"], data["owner"])
    ws.send(data["uuid"])


@app.route('/reserve/<uuid>')
def reserve_route(uuid):
    data = {'uuid': uuid}
    resa.reserve(data["uuid"], 'Aerouser')
    data = {"status": "ok"}
    resp = jsonify(data)
    resp.status_code = 200
    return resp


@sockets.route('/release')
def release(ws):
    data = json.loads(ws.receive())
    resa.release(data["uuid"])
    ws.send(data["uuid"])


@app.route('/deploy/<uuid>')
def deploy_route(uuid):
    data = {'uuid': uuid}
    server = oneview_client.server_hardware.get(data['uuid'])
    profile = oneview_client.server_profiles.get(server['serverProfileUri'])
    macaddress = get_mac(profile)
    flagpath = 'flags/' + macaddress
    if os.path.exists(flagpath):
        os.remove(flagpath)
    # Power off server
    powering(data, 'Off')
    time.sleep(10)
    # Power on server
    powering(data, 'On')
    data = {"status": "ok"}
    resp = jsonify(data)
    resp.status_code = 200
    return resp


@sockets.route('/deploy')
def deploy_ws(ws):
    data = json.loads(ws.receive())
    server = oneview_client.server_hardware.get(data['uuid'])
    profile = oneview_client.server_profiles.get(server['serverProfileUri'])
    macaddress = get_mac(profile)
    flagpath = 'flags/' + macaddress
    if os.path.exists(flagpath):
        os.remove(flagpath)
    # Power off server
    powering(data, 'Off')
    msg = data["uuid"] + "requested to stop."
    ws.send(msg)
    time.sleep(10)
    # Power on server
    powering(data, 'On')
    msg = data["uuid"] + "powered on."
    ws.send(msg)


@sockets.route('/console')
def console(ws):
    data = json.loads(ws.receive())
    remote_console_url = \
        oneview_client.server_hardware.get_java_remote_console_url(
            data["uuid"])
    msg = remote_console_url
    ws.send(msg["javaRemoteConsoleUrl"])


@app.route('/status/<uuid>')
def status_route(uuid):
    server_hardware_all = oneview_client.server_hardware.get_all()
    for server in server_hardware_all:
        if server['serverProfileUri'] is not None:
            profile = oneview_client.server_profiles.get(
                server['serverProfileUri'])
            if 'iPXE' in profile["name"]:
                data = define_status(server, profile)
    resp = jsonify(data)
    resp.status_code = 200
    return resp


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
    global config
    # Get hardware
    server_hardware_all = oneview_client.server_hardware.get_all()
    # Get templates
    templates = [
        oneview_client.server_profile_templates.get_by_name('Boot iPXE SY480'),
        oneview_client.server_profile_templates.get_by_name('Boot iPXE SY620')]
    # Craft required data
    data2print = []
    for server in server_hardware_all:
        applicable_profile = 'None'
        try:
            available480s = \
                oneview_client.server_profiles.get_available_servers(
                    serverHardwareTypeUri=templates[0]
                                                   ['serverHardwareTypeUri'])
            for srv in available480s:
                if server['uri'] == srv['serverHardwareUri']:
                    applicable_profile = '480'
        except TypeError:
            pass

        try:
            available620s = \
                oneview_client.server_profiles.get_available_servers(
                    serverHardwareTypeUri=templates[1]
                                                   ['serverHardwareTypeUri'])
            for srv in available620s:
                if server['uri'] == srv['serverHardwareUri']:
                    applicable_profile = '620'
        except TypeError:
            pass

        data2print.append({
            'shortModel': server['shortModel'],
            'serverProfileUri': server['serverProfileUri'],
            'name': server['name'],
            'uuid': server['uuid'],
            'powerState': server['powerState'],
            'owner': resa.get(server['uuid']),
            'applicable_profile': applicable_profile
            })
    html = render_template("available.html", data2print, config["ip"])
    return html


@app.route('/availablexml')
def availablexml():
    global config
    # Get hardware
    server_hardware_all = oneview_client.server_hardware.get_all()
    # Get templates
    templates = [oneview_client.server_profile_templates.get_by_name('Boot iPXE SY480'), oneview_client.server_profile_templates.get_by_name('Boot iPXE SY620')]
    # Craft required data
    data2print = []
    for server in server_hardware_all:
        applicable_profile = 'None'
        try:
            available480s = oneview_client.server_profiles.get_available_servers(serverHardwareTypeUri=templates[0]['serverHardwareTypeUri'])
            for srv in available480s:
                if server['uri'] == srv['serverHardwareUri']:
                    applicable_profile = '480'
        except TypeError:
            pass

        try:
            available620s = oneview_client.server_profiles.get_available_servers(serverHardwareTypeUri=templates[1]['serverHardwareTypeUri'])
            for srv in available620s:
                if server['uri'] == srv['serverHardwareUri']:
                    applicable_profile = '620'
        except TypeError:
            pass

        data2print.append({
            'shortModel': server['shortModel'],
            'serverProfileUri': server['serverProfileUri'],
            'name': server['name'],
            'uuid': server['uuid'],
            'powerState': server['powerState'],
            'owner': resa.get(server['uuid']),
            'applicable_profile': applicable_profile
            })
    html = render_template("availablexml.html", data2print, config["ip"])
    return html


@app.route('/ready2deploy')
def ready2deploy():
    global config
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
    html = render_template("ready2deploy.html", data2print, config["ip"])
    return html


@app.route('/use')
def deployed():
    global config
    # Get hardware
    server_hardware_all = oneview_client.server_hardware.get_all()
    # Craft required data
    data2print = []
    for server in server_hardware_all:
        data = {}
        if server['serverProfileUri'] is not None:
            profile = oneview_client.server_profiles.get(
                server['serverProfileUri'])
            if 'iPXE' in profile["name"]:
                macaddress = get_mac(profile)
                filename = "flags/" + macaddress
                if os.path.exists(filename):
                    data = read_tracefile(macaddress)
                    try:
                        data["ipaddress"]
                    except KeyError:
                        data["ipaddress"] = ''
                else:
                    data["ipaddress"] = ''

                data2print.append({
                    'shortModel': server['shortModel'],
                    'name': server['name'],
                    'uuid': server['uuid'],
                    'macaddress': macaddress,
                    'powerState': server['powerState'],
                    'owner': resa.get(server['uuid']),
                    'ipaddress': data["ipaddress"]
                    })
    html = render_template("deployed.html", data2print, config["ip"])
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
    write_tracefile(macaddress, {"manufacturer": manufacturer,
                                 "status": "bootipxe",
                                 "macaddress": macaddress})

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

    return write_tracefile(macaddress, {"status": "deployed"})


@app.route('/deploy/os', methods=["POST"])
def deploy_osready():
    # Write a trace file
    try:
        macaddress = request.json['macaddress']
        ipaddress = request.json['ipaddress']
    except KeyError:
        raise InvalidUsage(
            'Invalid key provided should be macaddress and ipaddress',
            status_code=400)
    return write_tracefile(macaddress, {"status": "osready",
                                        "ipaddress": ipaddress})


def render_template(template, values=None, config=None):
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
        data = template.render(r=values, config=config)

    return data


def write_tracefile(macaddress, newdata):
    data = {}
    if not macaddress:
        raise ValueError("macaddress parameter can not be empty.")
    filename = "flags/" + macaddress
    if os.path.exists(filename):
        data = read_tracefile(macaddress)
    # Update data
    data.update(newdata)
    with open(filename, 'w') as tracefile:
        json.dump(data, tracefile)
        tracefile.close()
        data = {"status": "ok"}
        resp = jsonify(data)
        resp.status_code = 200
        return resp


def read_tracefile(macaddress):
    filename = "flags/" + macaddress
    with open(filename, 'r') as tracefile:
        data = json.load(tracefile)
        return data


def define_status(server, profile):
    data = {}
    data["status"] = ''
    data["ipaddress"] = ''
    data["manufacturer"] = ''
    status = ''
    ipaddress = ''
    manufacturer = ''
    macaddress = get_mac(profile)
    filename = "flags/" + macaddress
    if os.path.exists(filename):
        data = read_tracefile(macaddress)

    if (server["powerState"] == 'On' and data["status"] == "deployed"):
        status = 'OS deployed, rebooting'
    elif (server["powerState"] == 'On' and data["status"] == "osready"):
        status = 'System ready'
        ipaddress = data["ipaddress"]
    elif (server["powerState"] == 'On' and data["status"] == "bootipxe"):
        status = 'Deployment in progress'
        manufacturer = data["manufacturer"]
    elif (server["powerState"] == 'On'):
        status = 'PowerOn'
    elif (server["powerState"] == 'Off'):
        status = 'PowerOff'
    data = {"uuid": server["uuid"],
            "status": status,
            "macaddress": macaddress,
            "ipaddress": ipaddress,
            "manufacturer": manufacturer,
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
