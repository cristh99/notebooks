#!/usr/bin/env bash
set -euo pipefail

TESSERACT_SOURCE_COMMIT="8ee020e14cf5be4e3f0e9beb09b6b050a1871854"
TESSERACT_SOURCE_ROOT="/tmp/tesseract-5.3.4"

sudo apt-get update -qq
sudo apt-get install -y --allow-downgrades --no-install-recommends \
  autoconf=2.71-3 \
  automake=1:1.16.5-1.3ubuntu1 \
  ca-certificates=20240203 \
  g++=4:13.2.0-7ubuntu1 \
  git=1:2.54.0-0ppa1~ubuntu24.04.2 \
  libarchive-dev=3.7.2-2ubuntu0.7 \
  libcairo2-dev=1.18.0-3build1 \
  libcurl4-openssl-dev=8.5.0-2ubuntu10.8 \
  libicu-dev=74.2-1ubuntu3.1 \
  libjpeg-dev=8c-2ubuntu11 \
  libleptonica-dev=1.82.0-3build4 \
  libopenjp2-7-dev=2.5.0-2ubuntu0.4 \
  libpango1.0-dev=1.52.1+ds-1build1 \
  libpng-dev=1.6.43-5build1 \
  libtiff-dev=4.5.1+git230720-4ubuntu2.4 \
  libtool=2.4.7-7build1 \
  libwebp-dev=1.3.2-0.4build3 \
  make=4.3-4.1build2 \
  pkg-config=1.8.1-2build1 \
  tesseract-ocr-eng=1:4.1.0-2 \
  zlib1g-dev=1:1.3.dfsg-3.1ubuntu2.1

rm -rf "${TESSERACT_SOURCE_ROOT}"
git clone --filter=blob:none --no-checkout \
  https://github.com/tesseract-ocr/tesseract.git \
  "${TESSERACT_SOURCE_ROOT}"
git -C "${TESSERACT_SOURCE_ROOT}" fetch --depth 1 origin \
  "${TESSERACT_SOURCE_COMMIT}"
git -C "${TESSERACT_SOURCE_ROOT}" checkout --detach \
  "${TESSERACT_SOURCE_COMMIT}"
test "$(git -C "${TESSERACT_SOURCE_ROOT}" rev-parse HEAD)" = \
  "${TESSERACT_SOURCE_COMMIT}"

pushd "${TESSERACT_SOURCE_ROOT}"
./autogen.sh
./configure --disable-doc
make -j2
sudo make install
popd
sudo ldconfig

ENG_TRAINEDDATA="$(dpkg -L tesseract-ocr-eng | grep '/eng.traineddata$' | head -1)"
test -f "${ENG_TRAINEDDATA}"
sudo mkdir -p /usr/local/share/tessdata
sudo cp "${ENG_TRAINEDDATA}" /usr/local/share/tessdata/eng.traineddata
export TESSDATA_PREFIX=/usr/local/share/tessdata
if [[ -n "${GITHUB_ENV:-}" ]]; then
  echo "TESSDATA_PREFIX=${TESSDATA_PREFIX}" >> "${GITHUB_ENV}"
fi

python -m pip install --disable-pip-version-check --only-binary=:all: \
  Pillow==12.2.0 \
  numpy==2.2.6 \
  opencv-python-headless==4.10.0.84 \
  scikit-learn==1.8.0 \
  scipy==1.17.1 \
  threadpoolctl==3.6.0 \
  joblib==1.5.3 \
  pyarrow==18.1.0 \
  pytesseract==0.3.13 \
  duckdb==1.5.5 \
  packaging==26.3

first_line="$(/usr/local/bin/tesseract --version | head -1)"
test "${first_line}" = "tesseract 5.3.4"
test "$(python -c 'import platform; print(platform.python_version())')" = "3.11.15"
