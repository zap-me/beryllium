FROM elementsproject/lightningd:v0.11.1

# install extra rebalance plugin
RUN apt-get update
RUN apt-get install -y build-essential python3-dev python3-setuptools
COPY ./requirements.txt /tmp/requirements.txt
RUN pip3 install --upgrade pip
RUN pip3 install -r /tmp/requirements.txt
RUN mkdir /opt/lightningd_plugins
COPY ./rebalance.py /opt/lightningd_plugins/
COPY ./config.j2 /config.j2
# plumbing for --wallet replica
RUN mkdir /root/.lightning_replica
COPY ./entrypoint-shim.sh /entrypoint-shim.sh
RUN chmod +x /entrypoint-shim.sh
ENTRYPOINT [ "/usr/bin/tini", "-g", "--", "./entrypoint-shim.sh"]
