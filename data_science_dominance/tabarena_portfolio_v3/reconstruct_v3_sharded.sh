#!/usr/bin/env bash
set -euo pipefail
root='data_science_dominance/tabarena_portfolio_v3'
echo '012f32fc0eea68789c35d9826a7b0675dce99752b7a73b8b6d36974f43e7bb19  data_science_dominance/tabarena_portfolio_v3/transport/part_00.b64' | sha256sum -c -
echo '5cfd443d5c61dec3b090f20dc0b6c8ea3987cb43b5eb96b0f6a36fce1c3a5709  data_science_dominance/tabarena_portfolio_v3/transport/part_01.b64' | sha256sum -c -
echo 'b0da5f566dc7436345f4c0f2ecb43037389a8d13c65c917d7e99e8256dcf5587  data_science_dominance/tabarena_portfolio_v3/transport/part_02.b64' | sha256sum -c -
echo 'ffd7ae312219e40288fabe7552c15fb0d09464941b497b004acca9d9473339d8  data_science_dominance/tabarena_portfolio_v3/transport/part_03.b64' | sha256sum -c -
echo 'c5d300c58df1140cf8ae77b42be8cbc0dd53b4c11eb4ad0a48ee3b45d8240e59  data_science_dominance/tabarena_portfolio_v3/transport/part_04.b64' | sha256sum -c -
echo 'ecafdc8b8f0fc4a38af3fc232ad1575984d305064544b7f9c2facff08bab42f2  data_science_dominance/tabarena_portfolio_v3/transport/part_05.b64' | sha256sum -c -
echo 'f3de8e19ebda80917052406451cb7fade1e1be30b74efce2a3fd5cd4362deb88  data_science_dominance/tabarena_portfolio_v3/transport/part_06.b64' | sha256sum -c -
echo '2ff6a71c34bce0ef1d2ca30c9f31a10fd28d04e2572198cac891a09784492f44  data_science_dominance/tabarena_portfolio_v3/transport/part_07.b64' | sha256sum -c -
cat "$root"/transport/part_*.b64 > /tmp/v3.b64
echo '86b7be1c4b91c4fa22674968753d0febbab169f24a1f33f15c51a18702e07482  /tmp/v3.b64' | sha256sum -c -
base64 -d /tmp/v3.b64 > /tmp/v3.tar.gz
echo 'a9f76d0d1ab1473979bf998c81a035f11ccebd1a92f33fad42415153ef71c68d  /tmp/v3.tar.gz' | sha256sum -c -
tar xzf /tmp/v3.tar.gz -C .
echo '6b5927a854c5b2d565a6065f6c8807134ef52cf03e77803c7d6fcdc4b78a96ff  data_science_dominance/tabarena_portfolio_v3/dominance_v3.py' | sha256sum -c -
echo '8586c814949cf95a35c05c3e6505c7983ce5e8c626e8cbc86ed04aaa678d2152  data_science_dominance/tabarena_portfolio_v3/runner_v3.py' | sha256sum -c -
echo '8204cc0611a1c3f7bc6d3186295f4f4876cc8f01c965d49775a1c9b8ccff3edd  data_science_dominance/tabarena_portfolio_v3/tasks_v3.json' | sha256sum -c -
echo '794fedc960eb855a0ed03d745fb6443e78947b627f2d082c9447732e825398f3  data_science_dominance/tabarena_portfolio_v3/SOURCE_MANIFEST_V3.json' | sha256sum -c -
echo '31950a8a231e4216ffc00453b7f2ad72294348271fa6b33fca43f8f9af8e6e9f  data_science_dominance/tabarena_portfolio_v3/DEVELOPMENT_RECEIPT_V3.json' | sha256sum -c -
echo '6b0e275b6e60ec766ba5d8d19c27234c252bbcae22a3f7df6d0e3908f81e1c90  data_science_god_level/tabular_transfer/estimator.py' | sha256sum -c -
