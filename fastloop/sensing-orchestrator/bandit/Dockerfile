FROM python:3.9

RUN apt -y update && apt -y upgrade

ENV TZ=Etc/UTC

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y \
    autoconf automake build-essential ccache cmake \
    linux-cpupower doxygen ethtool fort77 g++ \
    gir1.2-gtk-3.0 git gobject-introspection gpsd gpsd-clients \
    inetutils-tools libasound2-dev libboost-all-dev libcomedi-dev \
    libcppunit-dev libfftw3-bin libfftw3-dev libfftw3-doc \
    libfontconfig1-dev libgmp-dev libgps-dev libgsl-dev \
    liblog4cpp5-dev libncurses6 libncurses-dev \
    libpulse-dev libqt5opengl5-dev libqwt-qt5-dev \
    libsdl2-dev libtool libudev-dev libusb-1.0-0 \
    libusb-1.0-0-dev libusb-dev libxi-dev libxrender-dev \
    libzmq3-dev libzmq5 ncurses-bin python3-cheetah \
    python3-click python3-click-plugins python3-click-threading \
    python3-dev python3-docutils python3-gi python3-gi-cairo \
    python3-gps python3-lxml python3-mako python3-numpy \
    python3-opengl python3-pyqt5 python3-requests \
    python3-scipy python3-setuptools python3-six python3-sphinx \
    python3-yaml python3-zmq python3-ruamel.yaml swig wget

RUN git clone https://github.com/EttusResearch/uhd /uhd

WORKDIR /uhd/host

RUN mkdir build

WORKDIR /uhd/host/build

RUN pip install mako

RUN apt -y install libuhd-dev uhd-host

RUN cmake .. -DENABLE_DOXYGEN=OFF 

ENV MAKEFLAGS="-j$(nproc)"

RUN make -j$(nproc)

RUN make install

RUN ldconfig

RUN export LD_LIBRARY_PATH=/usr/local/lib

RUN pip install requests

RUN uhd_images_downloader

ENV UHD_IMAGES_DIR=/usr/local/share/uhd/images

WORKDIR /app

COPY . .

RUN apt -y install python3-uhd python3-requests

ENTRYPOINT [ "python3.13", "-u", "app/main.py" ]