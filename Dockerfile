FROM debian
RUN apt-get update && apt-get install -y python-pip python-dev git
RUN apt-get install -y locales && echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen && locale-gen
RUN adduser --disabled-password --gecos "" user
ENV LANG en_US.UTF-8

WORKDIR /home/user
ADD . /home/user/agkyra

RUN git clone https://github.com/pyinstaller/pyinstaller.git
WORKDIR /home/user/agkyra
RUN python configure.py linux64 && python setup.py install
RUN chown user:user /home/user/agkyra/build
RUN chown user:user /home/user/agkyra/dist

USER user
ENV HOME /home/user
RUN ../pyinstaller/pyinstaller.py agkyra.spec
