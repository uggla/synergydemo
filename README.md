# synergydemo

A small application to highlight HPE Synergy hardware and especially the Oneview unified API.
This is a home made application that allow user to Reserve, deploy and run containers on the underlying hardware.

This application uses python oneview, docker libraries.

# Screenshots


# Prerequisites
* Configure isc-dhcpd using the configuration file provided in the conf directory.
* Configure tftp to boot iPXE.
* Add kickstart ks.txt provided in the conf directory within the Centos 7 repository.

# Installation
* Install git.
* Clone the repository.
* Create a virtual env.
* Install dependencies.
* Export OVLOGIN and OVPASSWD.
* Run the server.
