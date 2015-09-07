FROM debian
RUN apt-get update && apt-get install -y python-pip python-dev git wget vim
RUN mkdir /src && cd /src && git clone https://github.com/pyinstaller/pyinstaller.git
ADD . /src/agkyra
RUN apt-get install -y locales && echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen && locale-gen
ENV LANG en_US.UTF-8
RUN cd /src/agkyra && ./configure.sh linux64 && python setup.py install
RUN adduser --disabled-password --gecos "" --ingroup root user
RUN chmod -R g+w /src
RUN su -c "cd /src/agkyra && ../pyinstaller/pyinstaller.py agkyra.spec" user
