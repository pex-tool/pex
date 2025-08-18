# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

import pytest

from pex.pep_503 import ProjectName
from pex.pex import PEX
from testing import run_pex_command
from testing.pytest_utils.tmp import Tempdir

# N.B.: Generated via:
# pex3 lock create --style universal --interpreter-constraint ">=3.7" "coverage[toml]<7" --indent 2 -o lock.json
# pex3 lock export --format pep-751 -o pylock.toml lock.json
PYLOCK = """\
lock-version = "1.0"
requires-python = ">=3.7"
extras = []
dependency-groups = []
default-groups = []
created-by = "pex"

[[packages]]
name = "coverage"
version = "6.5"
requires-python = ">=3.7"
dependencies = [
    {name = "tomli"},
]
sdist = {name = "coverage-6.5.0.tar.gz", url = "https://files.pythonhosted.org/packages/5c/66/38d1870cb7cf62da49add1d6803fdbcdef632b2808b5c80bcac35b7634d8/coverage-6.5.0.tar.gz", hashes = {sha256 = "f642e90754ee3e06b0e7e51bce3379590e76b7f76b708e1a71ff043f87025c84"}}
wheels = [
    {name = "coverage-6.5.0-pp36.pp37.pp38-none-any.whl", url = "https://files.pythonhosted.org/packages/6e/e6/b31a4b2aa9489da59b35ee0ea4259d6fe9b321a1eaa6492f19342d03d53b/coverage-6.5.0-pp36.pp37.pp38-none-any.whl", hashes = {sha256 = "1431986dac3923c5945271f169f59c45b8802a114c8f548d611f2015133df77a"}},
    {name = "coverage-6.5.0-cp39-cp39-win_amd64.whl", url = "https://files.pythonhosted.org/packages/b6/08/a88a9f3a11bb2d97c7a6719535a984b009728433838fbc65766488867c80/coverage-6.5.0-cp39-cp39-win_amd64.whl", hashes = {sha256 = "fc2af30ed0d5ae0b1abdb4ebdce598eafd5b35397d4d75deb341a614d333d987"}},
    {name = "coverage-6.5.0-cp39-cp39-win32.whl", url = "https://files.pythonhosted.org/packages/8f/17/e1d54e0e5a1e82dea1b1d9463dfe347ded58037beda00d326f943a9ef2d4/coverage-6.5.0-cp39-cp39-win32.whl", hashes = {sha256 = "d9ecf0829c6a62b9b573c7bb6d4dcd6ba8b6f80be9ba4fc7ed50bf4ac9aecd72"}},
    {name = "coverage-6.5.0-cp39-cp39-musllinux_1_1_x86_64.whl", url = "https://files.pythonhosted.org/packages/c8/e8/e712b61abf1282ce3ac9826473ab4b245a4319303cce2e4115a8de1435f2/coverage-6.5.0-cp39-cp39-musllinux_1_1_x86_64.whl", hashes = {sha256 = "723e8130d4ecc8f56e9a611e73b31219595baa3bb252d539206f7bbbab6ffc1f"}},
    {name = "coverage-6.5.0-cp39-cp39-musllinux_1_1_i686.whl", url = "https://files.pythonhosted.org/packages/58/2c/213861cec1d9f6451d29c0b1838769b558f6a8c6844b001f6e98c37c4b1b/coverage-6.5.0-cp39-cp39-musllinux_1_1_i686.whl", hashes = {sha256 = "42eafe6778551cf006a7c43153af1211c3aaab658d4d66fa5fcc021613d02518"}},
    {name = "coverage-6.5.0-cp39-cp39-musllinux_1_1_aarch64.whl", url = "https://files.pythonhosted.org/packages/a8/d9/b367c52cb1297414ba967e38fe9b5338ee4700a2d1592fc78532dc9f882f/coverage-6.5.0-cp39-cp39-musllinux_1_1_aarch64.whl", hashes = {sha256 = "7b6be138d61e458e18d8e6ddcddd36dd96215edfe5f1168de0b1b32635839b62"}},
    {name = "coverage-6.5.0-cp39-cp39-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", url = "https://files.pythonhosted.org/packages/6b/f2/919f0fdc93d3991ca074894402074d847be8ac1e1d78e7e9e1c371b69a6f/coverage-6.5.0-cp39-cp39-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hashes = {sha256 = "8f830ed581b45b82451a40faabb89c84e1a998124ee4212d440e9c6cf70083e5"}},
    {name = "coverage-6.5.0-cp39-cp39-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", url = "https://files.pythonhosted.org/packages/d6/0f/012a7370aaf61123a222b34b657dedc63e03ce2af8d064ac5c5afe14f29c/coverage-6.5.0-cp39-cp39-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", hashes = {sha256 = "265de0fa6778d07de30bcf4d9dc471c3dc4314a23a3c6603d356a3c9abc2dfcf"}},
    {name = "coverage-6.5.0-cp39-cp39-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", url = "https://files.pythonhosted.org/packages/18/95/27f80dcd8273171b781a19d109aeaed7f13d78ef6d1e2f7134a5826fd1b4/coverage-6.5.0-cp39-cp39-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hashes = {sha256 = "b9023e237f4c02ff739581ef35969c3739445fb059b060ca51771e69101efffe"}},
    {name = "coverage-6.5.0-cp39-cp39-macosx_11_0_arm64.whl", url = "https://files.pythonhosted.org/packages/63/e9/f23e8664ec4032d7802a1cf920853196bcbdce7b56408e3efe1b2da08f3c/coverage-6.5.0-cp39-cp39-macosx_11_0_arm64.whl", hashes = {sha256 = "95203854f974e07af96358c0b261f1048d8e1083f2de9b1c565e1be4a3a48cfc"}},
    {name = "coverage-6.5.0-cp39-cp39-macosx_10_9_x86_64.whl", url = "https://files.pythonhosted.org/packages/ea/52/c08080405329326a7ff16c0dfdb4feefaa8edd7446413df67386fe1bbfe0/coverage-6.5.0-cp39-cp39-macosx_10_9_x86_64.whl", hashes = {sha256 = "633713d70ad6bfc49b34ead4060531658dc6dfc9b3eb7d8a716d5873377ab745"}},
    {name = "coverage-6.5.0-cp38-cp38-win_amd64.whl", url = "https://files.pythonhosted.org/packages/06/f1/5177428c35f331f118e964f727f79e3a3073a10271a644c8361d3cea8bfd/coverage-6.5.0-cp38-cp38-win_amd64.whl", hashes = {sha256 = "7ccf362abd726b0410bf8911c31fbf97f09f8f1061f8c1cf03dfc4b6372848f6"}},
    {name = "coverage-6.5.0-cp38-cp38-win32.whl", url = "https://files.pythonhosted.org/packages/e9/f0/3be949bd129237553714149b1909d34c94137ca4b86e036bc7060431da18/coverage-6.5.0-cp38-cp38-win32.whl", hashes = {sha256 = "6d4817234349a80dbf03640cec6109cd90cba068330703fa65ddf56b60223a6d"}},
    {name = "coverage-6.5.0-cp38-cp38-musllinux_1_1_x86_64.whl", url = "https://files.pythonhosted.org/packages/e5/fb/11982f5faf2990d4d9159e01a12bbf0a7d7873893d4d2e2acec012ad69ae/coverage-6.5.0-cp38-cp38-musllinux_1_1_x86_64.whl", hashes = {sha256 = "e07f4a4a9b41583d6eabec04f8b68076ab3cd44c20bd29332c6572dda36f372e"}},
    {name = "coverage-6.5.0-cp38-cp38-musllinux_1_1_i686.whl", url = "https://files.pythonhosted.org/packages/a1/6b/7efeeffc7559150a705931b2144b936042c561e63ef248f0e0d9f4523d74/coverage-6.5.0-cp38-cp38-musllinux_1_1_i686.whl", hashes = {sha256 = "de3001a203182842a4630e7b8d1a2c7c07ec1b45d3084a83d5d227a3806f530f"}},
    {name = "coverage-6.5.0-cp38-cp38-musllinux_1_1_aarch64.whl", url = "https://files.pythonhosted.org/packages/a3/a0/4c59586df0511b18f7b59593672a4baadacef8f393024052d59c6222477c/coverage-6.5.0-cp38-cp38-musllinux_1_1_aarch64.whl", hashes = {sha256 = "dbdb91cd8c048c2b09eb17713b0c12a54fbd587d79adcebad543bc0cd9a3410b"}},
    {name = "coverage-6.5.0-cp38-cp38-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", url = "https://files.pythonhosted.org/packages/bd/a0/e263b115808226fdb2658f1887808c06ac3f1b579ef5dda02309e0d54459/coverage-6.5.0-cp38-cp38-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hashes = {sha256 = "6b07130585d54fe8dff3d97b93b0e20290de974dc8177c320aeaf23459219c0b"}},
    {name = "coverage-6.5.0-cp38-cp38-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", url = "https://files.pythonhosted.org/packages/02/7a/a45f3958442d50b9a930a62f0dba9ee502521213ebd016203c2890ea212f/coverage-6.5.0-cp38-cp38-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", hashes = {sha256 = "20c8ac5386253717e5ccc827caad43ed66fea0efe255727b1053a8154d952398"}},
    {name = "coverage-6.5.0-cp38-cp38-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", url = "https://files.pythonhosted.org/packages/40/3b/cd68cb278c4966df00158811ec1e357b9a7d132790c240fc65da57e10013/coverage-6.5.0-cp38-cp38-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hashes = {sha256 = "6c4459b3de97b75e3bd6b7d4b7f0db13f17f504f3d13e2a7c623786289dd670e"}},
    {name = "coverage-6.5.0-cp38-cp38-macosx_11_0_arm64.whl", url = "https://files.pythonhosted.org/packages/07/82/79fa21ceca9a9b091eb3c67e27eb648dade27b2c9e1eb23af47232a2a365/coverage-6.5.0-cp38-cp38-macosx_11_0_arm64.whl", hashes = {sha256 = "2198ea6fc548de52adc826f62cb18554caedfb1d26548c1b7c88d8f7faa8f6ba"}},
    {name = "coverage-6.5.0-cp38-cp38-macosx_10_9_x86_64.whl", url = "https://files.pythonhosted.org/packages/05/63/a789b462075395d34f8152229dccf92b25ca73eac05b3f6cd75fa5017095/coverage-6.5.0-cp38-cp38-macosx_10_9_x86_64.whl", hashes = {sha256 = "d900bb429fdfd7f511f868cedd03a6bbb142f3f9118c09b99ef8dc9bf9643c3c"}},
    {name = "coverage-6.5.0-cp37-cp37m-win_amd64.whl", url = "https://files.pythonhosted.org/packages/d6/00/3e12af83af2a46c1fd27b78486f404736934d0288bda4975119611a01cb3/coverage-6.5.0-cp37-cp37m-win_amd64.whl", hashes = {sha256 = "4a8dbc1f0fbb2ae3de73eb0bdbb914180c7abfbf258e90b311dcd4f585d44bd2"}},
    {name = "coverage-6.5.0-cp37-cp37m-win32.whl", url = "https://files.pythonhosted.org/packages/32/40/e2b1ffa42028365e3465d1340e7d390d096fc992dec2c80e4afed6361e83/coverage-6.5.0-cp37-cp37m-win32.whl", hashes = {sha256 = "b5604380f3415ba69de87a289a2b56687faa4fe04dbee0754bfcae433489316b"}},
    {name = "coverage-6.5.0-cp37-cp37m-musllinux_1_1_x86_64.whl", url = "https://files.pythonhosted.org/packages/64/7f/13f5d58f5ca41182d7020af5257c8fd08ddf33921d2a28cf66753571c278/coverage-6.5.0-cp37-cp37m-musllinux_1_1_x86_64.whl", hashes = {sha256 = "12adf310e4aafddc58afdb04d686795f33f4d7a6fa67a7a9d4ce7d6ae24d949f"}},
    {name = "coverage-6.5.0-cp37-cp37m-musllinux_1_1_i686.whl", url = "https://files.pythonhosted.org/packages/76/44/78c1936c2bd9e7705f170d5e413ed34d9d6d7d0324757786627f88df1514/coverage-6.5.0-cp37-cp37m-musllinux_1_1_i686.whl", hashes = {sha256 = "851cf4ff24062c6aec510a454b2584f6e998cada52d4cb58c5e233d07172e50c"}},
    {name = "coverage-6.5.0-cp37-cp37m-musllinux_1_1_aarch64.whl", url = "https://files.pythonhosted.org/packages/cd/48/65d314e702b4a7095ea96da0a319a5a377e594354a4a6badde483832bb5a/coverage-6.5.0-cp37-cp37m-musllinux_1_1_aarch64.whl", hashes = {sha256 = "255758a1e3b61db372ec2736c8e2a1fdfaf563977eedbdf131de003ca5779b7d"}},
    {name = "coverage-6.5.0-cp37-cp37m-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", url = "https://files.pythonhosted.org/packages/0d/ef/8735875a8dc09e1c4e484a5436c8b4148731b70daccc6f203c50b05e7505/coverage-6.5.0-cp37-cp37m-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hashes = {sha256 = "027018943386e7b942fa832372ebc120155fd970837489896099f5cfa2890f79"}},
    {name = "coverage-6.5.0-cp37-cp37m-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", url = "https://files.pythonhosted.org/packages/6b/ba/ef67c1e859b8ddd8cafb81199986ff702efcd4ee5d373670a0bc0a293d1f/coverage-6.5.0-cp37-cp37m-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", hashes = {sha256 = "94e2565443291bd778421856bc975d351738963071e9b8839ca1fc08b42d4bef"}},
    {name = "coverage-6.5.0-cp37-cp37m-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", url = "https://files.pythonhosted.org/packages/85/03/9dcc8b7e269cfeaf5519d433d841a7d78f283c5fb016385d4690e1aedfc1/coverage-6.5.0-cp37-cp37m-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hashes = {sha256 = "f4f05d88d9a80ad3cac6244d36dd89a3c00abc16371769f1340101d3cb899fc3"}},
    {name = "coverage-6.5.0-cp37-cp37m-macosx_10_9_x86_64.whl", url = "https://files.pythonhosted.org/packages/61/a6/af54588e2091693026df94b09106ee10dcbcdc8c9b2c3989149e6e44a324/coverage-6.5.0-cp37-cp37m-macosx_10_9_x86_64.whl", hashes = {sha256 = "4433b90fae13f86fafff0b326453dd42fc9a639a0d9e4eec4d366436d1a41b6d"}},
    {name = "coverage-6.5.0-cp311-cp311-win_amd64.whl", url = "https://files.pythonhosted.org/packages/e6/24/7fe8ededb4060dd8c3f1d86cb624fcb3452f66fbef5051ed7fab126c5c0c/coverage-6.5.0-cp311-cp311-win_amd64.whl", hashes = {sha256 = "bc8ef5e043a2af066fa8cbfc6e708d58017024dc4345a1f9757b329a249f041b"}},
    {name = "coverage-6.5.0-cp311-cp311-win32.whl", url = "https://files.pythonhosted.org/packages/ff/27/339089b558672f04e62d0cd2d49b9280270bad3bc95de24e7eb03deb4638/coverage-6.5.0-cp311-cp311-win32.whl", hashes = {sha256 = "98e8a10b7a314f454d9eff4216a9a94d143a7ee65018dd12442e898ee2310578"}},
    {name = "coverage-6.5.0-cp311-cp311-musllinux_1_1_x86_64.whl", url = "https://files.pythonhosted.org/packages/4b/66/6e588f5dfc93ccedd06d6785c8143f17bb92b89247d50128d8789e9588d0/coverage-6.5.0-cp311-cp311-musllinux_1_1_x86_64.whl", hashes = {sha256 = "cca4435eebea7962a52bdb216dec27215d0df64cf27fc1dd538415f5d2b9da6b"}},
    {name = "coverage-6.5.0-cp311-cp311-musllinux_1_1_i686.whl", url = "https://files.pythonhosted.org/packages/78/98/253ce0cfcc3b352d3072940940ed44a035614f2abe781477f77038d21d9f/coverage-6.5.0-cp311-cp311-musllinux_1_1_i686.whl", hashes = {sha256 = "1ef221513e6f68b69ee9e159506d583d31aa3567e0ae84eaad9d6ec1107dddaa"}},
    {name = "coverage-6.5.0-cp311-cp311-musllinux_1_1_aarch64.whl", url = "https://files.pythonhosted.org/packages/ac/bc/c9d4fd6b3494d2cc1e26f4b98eb19206b92a59094617ad02d5689ac9d3c4/coverage-6.5.0-cp311-cp311-musllinux_1_1_aarch64.whl", hashes = {sha256 = "a6b7d95969b8845250586f269e81e5dfdd8ff828ddeb8567a4a2eaa7313460c4"}},
    {name = "coverage-6.5.0-cp311-cp311-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", url = "https://files.pythonhosted.org/packages/6a/63/8e82513b7e4a1b8d887b4e85c1c2b6c9b754a581b187c0b084f3330ac479/coverage-6.5.0-cp311-cp311-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hashes = {sha256 = "a8fb6cf131ac4070c9c5a3e21de0f7dc5a0fbe8bc77c9456ced896c12fcdad91"}},
    {name = "coverage-6.5.0-cp311-cp311-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", url = "https://files.pythonhosted.org/packages/89/58/5ec19b43a6511288511f64fc4763d95af8403f5926e7e4556e6b29b03a26/coverage-6.5.0-cp311-cp311-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", hashes = {sha256 = "33a7da4376d5977fbf0a8ed91c4dffaaa8dbf0ddbf4c8eea500a2486d8bc4d7b"}},
    {name = "coverage-6.5.0-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", url = "https://files.pythonhosted.org/packages/36/f3/5cbd79cf4cd059c80b59104aca33b8d05af4ad5bf5b1547645ecee716378/coverage-6.5.0-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hashes = {sha256 = "c4ed2820d919351f4167e52425e096af41bfabacb1857186c1ea32ff9983ed75"}},
    {name = "coverage-6.5.0-cp311-cp311-macosx_10_9_x86_64.whl", url = "https://files.pythonhosted.org/packages/50/cf/455930004231fa87efe8be06d13512f34e070ddfee8b8bf5a050cdc47ab3/coverage-6.5.0-cp311-cp311-macosx_10_9_x86_64.whl", hashes = {sha256 = "4a5375e28c5191ac38cca59b38edd33ef4cc914732c916f2929029b4bfb50795"}},
    {name = "coverage-6.5.0-cp310-cp310-win_amd64.whl", url = "https://files.pythonhosted.org/packages/ae/a3/f45cb5d32de0751863945d22083c15eb8854bb53681b2e792f2066c629b9/coverage-6.5.0-cp310-cp310-win_amd64.whl", hashes = {sha256 = "59f53f1dc5b656cafb1badd0feb428c1e7bc19b867479ff72f7a9dd9b479f10e"}},
    {name = "coverage-6.5.0-cp310-cp310-win32.whl", url = "https://files.pythonhosted.org/packages/11/9e/7afba355bdabc550b3b2669e3432e71aec87d79400372d7686c09aab0acf/coverage-6.5.0-cp310-cp310-win32.whl", hashes = {sha256 = "5dbec3b9095749390c09ab7c89d314727f18800060d8d24e87f01fb9cfb40b32"}},
    {name = "coverage-6.5.0-cp310-cp310-musllinux_1_1_x86_64.whl", url = "https://files.pythonhosted.org/packages/c0/18/2a0a9b3c29376ce04ceb7ca2948559dad76409a2c9b3f664756581101e16/coverage-6.5.0-cp310-cp310-musllinux_1_1_x86_64.whl", hashes = {sha256 = "11b990d520ea75e7ee8dcab5bc908072aaada194a794db9f6d7d5cfd19661e5a"}},
    {name = "coverage-6.5.0-cp310-cp310-musllinux_1_1_i686.whl", url = "https://files.pythonhosted.org/packages/2f/8b/ca3fe3cfbd66d63181f6e6a06b8b494bb327ba8222d2fa628b392b9ad08a/coverage-6.5.0-cp310-cp310-musllinux_1_1_i686.whl", hashes = {sha256 = "a1170fa54185845505fbfa672f1c1ab175446c887cce8212c44149581cf2d466"}},
    {name = "coverage-6.5.0-cp310-cp310-musllinux_1_1_aarch64.whl", url = "https://files.pythonhosted.org/packages/10/9e/68e384940179713640743a010ac7f7c813d1087c8730a9c0bdfa73bdffd7/coverage-6.5.0-cp310-cp310-musllinux_1_1_aarch64.whl", hashes = {sha256 = "97117225cdd992a9c2a5515db1f66b59db634f59d0679ca1fa3fe8da32749cae"}},
    {name = "coverage-6.5.0-cp310-cp310-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", url = "https://files.pythonhosted.org/packages/3c/7d/d5211ea782b193ab8064b06dc0cc042cf1a4ca9c93a530071459172c550f/coverage-6.5.0-cp310-cp310-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hashes = {sha256 = "af4fffaffc4067232253715065e30c5a7ec6faac36f8fc8d6f64263b15f74db0"}},
    {name = "coverage-6.5.0-cp310-cp310-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", url = "https://files.pythonhosted.org/packages/13/f3/c6025ba30f2ce21d20d5332c3819880fe8afdfc008c2e2f9c075c7b67543/coverage-6.5.0-cp310-cp310-manylinux_2_5_i686.manylinux1_i686.manylinux_2_17_i686.manylinux2014_i686.whl", hashes = {sha256 = "83516205e254a0cb77d2d7bb3632ee019d93d9f4005de31dca0a8c3667d5bc04"}},
    {name = "coverage-6.5.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", url = "https://files.pythonhosted.org/packages/15/b0/3639d84ee8a900da0cf6450ab46e22517e4688b6cec0ba8ab6f8166103a2/coverage-6.5.0-cp310-cp310-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hashes = {sha256 = "b4a5be1748d538a710f87542f22c2cad22f80545a847ad91ce45e77417293eb4"}},
    {name = "coverage-6.5.0-cp310-cp310-macosx_11_0_arm64.whl", url = "https://files.pythonhosted.org/packages/89/a2/cbf599e50bb4be416e0408c4cf523c354c51d7da39935461a9687e039481/coverage-6.5.0-cp310-cp310-macosx_11_0_arm64.whl", hashes = {sha256 = "784f53ebc9f3fd0e2a3f6a78b2be1bd1f5575d7863e10c6e12504f240fd06660"}},
    {name = "coverage-6.5.0-cp310-cp310-macosx_10_9_x86_64.whl", url = "https://files.pythonhosted.org/packages/c4/8d/5ec7d08f4601d2d792563fe31db5e9322c306848fec1e65ec8885927f739/coverage-6.5.0-cp310-cp310-macosx_10_9_x86_64.whl", hashes = {sha256 = "ef8674b0ee8cc11e2d574e3e2998aea5df5ab242e012286824ea3c6970580e53"}},
]

[[packages]]
name = "tomli"
version = "2.0.1"
marker = "python_full_version <= '3.11.0a6'"
requires-python = ">=3.7"
sdist = {name = "tomli-2.0.1.tar.gz", url = "https://files.pythonhosted.org/packages/c0/3f/d7af728f075fb08564c5949a9c95e44352e23dee646869fa104a3b2060a3/tomli-2.0.1.tar.gz", hashes = {sha256 = "de526c12914f0c550d15924c62d72abc48d6fe7364aa87328337a31007fe8a4f"}}
wheels = [
    {name = "tomli-2.0.1-py3-none-any.whl", url = "https://files.pythonhosted.org/packages/97/75/10a9ebee3fd790d20926a90a2547f0bf78f371b2f13aa822c759680ca7b9/tomli-2.0.1-py3-none-any.whl", hashes = {sha256 = "939de3e7a6161af0c887ef91b7d41a53e7c5a1ca976325f429cb46ea9bc30ecc"}},
]
"""


@pytest.mark.skipif(
    sys.version_info < (3, 7), reason="The lock under test requires Python `>=3.7`."
)
def test_pylock_no_reqs_some_deps_deselected_via_marker(tmpdir):
    # type: (Tempdir) -> None

    with open(tmpdir.join("pylock.toml"), "w") as fp:
        fp.write(PYLOCK)

    pex_root = tmpdir.join("pex-root")
    pex_file = tmpdir.join("coverage.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "--pylock",
            fp.name,
            "-o",
            pex_file,
        ]
    ).assert_success()

    pex = PEX(pex_file)
    actual_dists = {dist.project_name for dist in pex.iter_distributions()}
    expected_dists = (
        {ProjectName("coverage"), ProjectName("tomli")}
        if sys.version_info <= (3, 11, 0, "alpha", 6)
        else {ProjectName("coverage")}
    )
    assert expected_dists == actual_dists
    assert ["coverage==6.5"] == list(pex.pex_info().requirements)
