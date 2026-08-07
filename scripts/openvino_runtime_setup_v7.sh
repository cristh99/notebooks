#!/usr/bin/env bash
set -euo pipefail

TESSERACT_SOURCE_COMMIT="8ee020e14cf5be4e3f0e9beb09b6b050a1871854"
TESSERACT_SOURCE_ROOT="/tmp/tesseract-5.3.4"

# Package repositories are moving installation inputs, not scientific identity.
# The preexecution gate later compares the complete executable dependency closure
# against the immutable runtime artifact and fails before any OpenVINO source read.
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  autoconf automake libtool pkg-config g++ make git ca-certificates \
  libleptonica-dev libpng-dev libjpeg-dev libtiff-dev zlib1g-dev \
  libwebp-dev libopenjp2-7-dev libarchive-dev libcurl4-openssl-dev \
  libicu-dev libpango1.0-dev libcairo2-dev tesseract-ocr-eng

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
