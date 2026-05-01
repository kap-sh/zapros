# Changelog

## [0.11.0](https://github.com/kap-sh/zapros/compare/v0.10.0...v0.11.0) (2026-05-01)


### Features

* allow PathMatcher to match url using regex ([#29](https://github.com/kap-sh/zapros/issues/29)) ([c61e454](https://github.com/kap-sh/zapros/commit/c61e454b2862412393e7ddda73b0584e493f8dec))
* **asgi:** add Trio backend support to AsgiHandler ([1ed340f](https://github.com/kap-sh/zapros/commit/1ed340f7e35770b719f85f27da74e876c9099f6d))


### Chores

* add parser for Connection header ([367e402](https://github.com/kap-sh/zapros/commit/367e40230252435d36b126e22ff845a294af260d))
* explicitly set build-system in pyproject.toml ([aaa6e56](https://github.com/kap-sh/zapros/commit/aaa6e56b6949db08c31a1ccb891952ed136c26ed))


### Refactors

* simplify asgi handler by buffering the bodies ([b84e1e1](https://github.com/kap-sh/zapros/commit/b84e1e1067a7b6fec156333d51cc1a771843d458))

## [0.10.0](https://github.com/kap-sh/zapros/compare/v0.9.0...v0.10.0) (2026-04-27)


### Features

* add mock call tracking helpers ([#27](https://github.com/kap-sh/zapros/issues/27)) ([f86c588](https://github.com/kap-sh/zapros/commit/f86c588f9858c6ed010d4274eec12b5d1fda7131))
* **client:** add base_url parameter for URL resolution ([2274816](https://github.com/kap-sh/zapros/commit/2274816208a6966723bf34972a4571b2cc348fa4))


### Bug Fixes

* make mypy happy with base handler shape ([6490251](https://github.com/kap-sh/zapros/commit/6490251e4aaf674cf44ff76bc7c7b7eee06cf476))


### Documentation

* Improve wording of what `mock_http` patches ([#26](https://github.com/kap-sh/zapros/issues/26)) ([fab280c](https://github.com/kap-sh/zapros/commit/fab280ccd58a38e420989f5b6ce7dcd1bc005484))
* mock_http should be used as sync context manager ([#23](https://github.com/kap-sh/zapros/issues/23)) ([fd3063c](https://github.com/kap-sh/zapros/commit/fd3063c6c1f5b42f401cd31dad57f1f18092e75b))
* separate matchers documentation ([6065c3b](https://github.com/kap-sh/zapros/commit/6065c3bad47b1bef3fbacbf48c6b737c34f2ebac))
* suggest avoiding ([2b67277](https://github.com/kap-sh/zapros/commit/2b6727722b23ac69707866cd36fc7dfab1b5ea34))

## [0.9.0](https://github.com/kap-sh/zapros/compare/v0.8.0...v0.9.0) (2026-04-24)


### Bug Fixes

* **pyodide:** strip out content-encoding header as fetch always decompresses ([14ef378](https://github.com/kap-sh/zapros/commit/14ef378cefa38a65207bcb6e0d9c725fb494f86d))


### Documentation

* fix the browser example, use CORS-free endpoint ([1f9e0ab](https://github.com/kap-sh/zapros/commit/1f9e0ab97eafaf12f8e1a95d005abddc5a86513d))

## [0.8.0](https://github.com/kap-sh/zapros/compare/v0.7.0...v0.8.0) (2026-04-24)


### Chores

* add CI test for pyodide support ([3c03a8f](https://github.com/kap-sh/zapros/commit/3c03a8f4200f57e25cd36c2898fe523e1bf0766d))
* release 0.8.0 ([3966f38](https://github.com/kap-sh/zapros/commit/3966f38ec6924fdbd1ddd4d63d5953c324f0333b))


### Documentation

* document how to use zapros in browser ([c5ee3dc](https://github.com/kap-sh/zapros/commit/c5ee3dcb1943ae7df7f0ff54cca2bb321999ef08))

## [0.7.0](https://github.com/kap-sh/zapros/compare/v0.6.0...v0.7.0) (2026-04-19)


### ⚠ BREAKING CHANGES

* **models:** split Response.content into _source and _content

### Features

* add ContentType header parsing and validation ([43984d5](https://github.com/kap-sh/zapros/commit/43984d556ba334351ab86c35df4d356e23a7e11a))
* add Response.consumed flag ([6ff277b](https://github.com/kap-sh/zapros/commit/6ff277b7a7a7d20f87e3e849e9fc4d9acbb9dc8c))


### Bug Fixes

* **caching:** properly handle cases when body was consumed before reaching cache ([d68cbc0](https://github.com/kap-sh/zapros/commit/d68cbc0c58f63e5121fb47ef4e8ac8e248ffd898))


### Chores

* bump ry version, simplify ry.yml ([ed05152](https://github.com/kap-sh/zapros/commit/ed051528aae87dcb1384a027caf8b9bf7787f6cb))
* disable release-please prerelease mode ([7fe0f3a](https://github.com/kap-sh/zapros/commit/7fe0f3aea51a25940c51b07dd312aac9283afa55))
* generate more sync code ([ef19b40](https://github.com/kap-sh/zapros/commit/ef19b40741975c954457b96e8264d1f371754255))


### Documentation

* fix typo in cassettes page ([4d086bc](https://github.com/kap-sh/zapros/commit/4d086bcbe574947ba74f6c9daae7637404d5ceaf))


### Refactors

* **cassettes:** deprecate Cassette, move some arguments to CassetteMiddleware ([a2e4eeb](https://github.com/kap-sh/zapros/commit/a2e4eeb9bdad964813c49e85de693ea26f4e3c40))
* **internal:** rename _source to _content ([1793b9b](https://github.com/kap-sh/zapros/commit/1793b9bb3a4fbb423f8324ec8a48603dda9500f2))
* **models:** split Response.content into _source and _content ([be45aea](https://github.com/kap-sh/zapros/commit/be45aead4f2c8482b4d36a9227959e5d7ea3774c))
* simplify cassette url normalizer ([1f0a304](https://github.com/kap-sh/zapros/commit/1f0a30403629a000b15d2b7472a044ab3b732165))
* simplify zapros to hishel conversion ([62e9f83](https://github.com/kap-sh/zapros/commit/62e9f83e74f857c1d74d7af3a0e87f018f69cf25))

## [0.6.0](https://github.com/kap-sh/zapros/compare/v0.5.1...v0.6.0) (2026-04-12)


### Features

* add support for trio ([e4c2469](https://github.com/kap-sh/zapros/commit/e4c24692f0c2dcf4aa8ec64b440cc46cecb6f42d))
* better exceptions mapping ([79ecc9c](https://github.com/kap-sh/zapros/commit/79ecc9cf0648dfc98c696f63eb9a5b6c1dbfb505))


### Chores

* bump ry version, get rid of bunch of ids ([5c166f8](https://github.com/kap-sh/zapros/commit/5c166f8b50bf8261469e7b9cfe253e1401a89837))
* bump ry version, tidy up tests ([311871f](https://github.com/kap-sh/zapros/commit/311871f3bc5832f27898d0f258dda87dc4190172))
* update uv.lock ([daff37b](https://github.com/kap-sh/zapros/commit/daff37beea572337b930d793f03e7733b0b5e6fa))

## [0.5.1](https://github.com/kap-sh/zapros/compare/zapros-v0.5.0...zapros-v0.5.1) (2026-04-08)


### Features

* add support for socks proxy ([550a483](https://github.com/kap-sh/zapros/commit/550a483c8f2064fb7a4a2909f23bcf0b055acdf0))
* **api:** add DNSResolutionError ([e88f282](https://github.com/kap-sh/zapros/commit/e88f2824a0d61f26a8410004a7bbd1c2bed2286a))
* **api:** add SSLError ([6763281](https://github.com/kap-sh/zapros/commit/6763281b1b40227e671435bc2a8008e3facf527c))
* **api:** add support for Response.raise_for_status ([a4f6784](https://github.com/kap-sh/zapros/commit/a4f678447f645481352da0a7b97c90cb5ace730e))
* replace unasync script with ry ([6761cd1](https://github.com/kap-sh/zapros/commit/6761cd175160d95713de1436216fa2ed8e977c6d))


### Bug Fixes

* do not buffer the response data in `iter_bytes` ([ef93fd1](https://github.com/kap-sh/zapros/commit/ef93fd19229cf8268cdded23eaa23a4b4018c1a9))

## [0.5.0](https://github.com/kap-sh/zapros/compare/zapros-v0.4.0...zapros-v0.5.0) (2026-04-04)


### ⚠ BREAKING CHANGES

* deprecate `atext` and `ajson` helpers

### Features

* add ZaprosError ([e7ecaea](https://github.com/kap-sh/zapros/commit/e7ecaeaa8d19be2527ea1cc513e942f42ff686af))
* expose `AsyncIOTransport` and `SyncTransport` classes ([0b6ef8a](https://github.com/kap-sh/zapros/commit/0b6ef8aba4bf646694647afd045f9d1d070a25ea))


### Documentation

* add docs for std handlers ([eac0ca1](https://github.com/kap-sh/zapros/commit/eac0ca1ccea26d17967626ef21e85065e9ff59fc))


### Code Refactoring

* deprecate `atext` and `ajson` helpers ([0ed8d08](https://github.com/kap-sh/zapros/commit/0ed8d08a1a2ce78434778d9f05fd9edec32bcf6c))

## [0.4.0](https://github.com/kap-sh/zapros/compare/zapros-v0.3.0...zapros-v0.4.0) (2026-04-04)


### ⚠ BREAKING CHANGES

* **types:** improve handler type annotations and deprecate misnamed middlewares

### Features

* add `ProxyMiddleware` ([495053e](https://github.com/kap-sh/zapros/commit/495053ee43e3c3009cc861f36e8ec4a0c0c074e3))
* **io:** add pluggable network transports ([408ddde](https://github.com/kap-sh/zapros/commit/408dddeb30c509c19403fc49a15209df181319e8))
* **io:** properly handle TLS-in-TLS upgrades ([408ddde](https://github.com/kap-sh/zapros/commit/408dddeb30c509c19403fc49a15209df181319e8))


### Bug Fixes

* **handlers:** handle 101 websocket upgrade responses ([035eb2e](https://github.com/kap-sh/zapros/commit/035eb2eae3e18cef4f00b322448c6801077e41a4))
* make connection pooling proxy-aware ([3c64504](https://github.com/kap-sh/zapros/commit/3c64504b7369f2cf9e682815f1ae99de20f88034))
* **pool:** narrow down some broad type catches ([db5cb6c](https://github.com/kap-sh/zapros/commit/db5cb6c02ecb0513747be1afa273b286619f186c))
* **proxies:** respect credentials in the proxy url ([5852aa6](https://github.com/kap-sh/zapros/commit/5852aa611887158a4284d5c65185e1c73d7e403e))
* remove body-related arguments from get and head methods ([37fc100](https://github.com/kap-sh/zapros/commit/37fc100c020df6b36cc5334dc11b8ec54ec3a82c))
* return usable handoff transport for 101 responses ([78a0a1e](https://github.com/kap-sh/zapros/commit/78a0a1e5096995f007a7454528b1ced15ed7aba0))
* **types:** correct `next_handler` type annotations in handlers ([f174810](https://github.com/kap-sh/zapros/commit/f17481082522d8276d5969d753fd9b631a112f55))
* **types:** improve handler type annotations and deprecate misnamed middlewares ([2376086](https://github.com/kap-sh/zapros/commit/2376086b4e4c385cbb9f970d8d3853ca189a353a))


### Documentation

* add docs for proxies ([5852aa6](https://github.com/kap-sh/zapros/commit/5852aa611887158a4284d5c65185e1c73d7e403e))

## [0.3.0](https://github.com/kap-sh/zapros/compare/zapros-v0.2.3...zapros-v0.3.0) (2026-03-21)


### Features

* add URLSearchParams to public API ([739c2ac](https://github.com/kap-sh/zapros/commit/739c2ac4f1754becb33140cd6a58fb366e9317b4))
* **perf:** use happy eyeballs by default in async handler ([793f2a2](https://github.com/kap-sh/zapros/commit/793f2a277fc20c0199c1bb612942e5894b0c500c))


### Bug Fixes

* ensure Response.aclose/close properly releases stream resources ([4d08138](https://github.com/kap-sh/zapros/commit/4d081383e23ca6de4ddc8d8fbf0fd37eb0f9373b))


### Documentation

* add async/sync separation guide with error links ([6841ef6](https://github.com/kap-sh/zapros/commit/6841ef6e4c6e76813799365bb3c7a50f8ebfaff5))
* add basic benchmark example ([89e711f](https://github.com/kap-sh/zapros/commit/89e711fb6c905accdd2d62c50a0aadab63f5c876))
* add OAuth authorization code flow example ([e286ec9](https://github.com/kap-sh/zapros/commit/e286ec9d3466cef716432f4dce15b3b49d8147e8))
* fix caching feature name ([a575bbe](https://github.com/kap-sh/zapros/commit/a575bbe0e286975c3ce17162f4c9e34cc18c4045))


### Miscellaneous Chores

* release 0.3.0 ([9eae1b3](https://github.com/kap-sh/zapros/commit/9eae1b372b0e7a42474b1fb6fcec41babd7b2242))

## [0.2.3](https://github.com/kap-sh/zapros/compare/zapros-v0.2.2...zapros-v0.2.3) (2026-03-14)


### Bug Fixes

* do not try to import pyreqwest on python3.10 ([fb968d7](https://github.com/kap-sh/zapros/commit/fb968d71a558938b528f3d8081f5205a3f881bca))
* fix support for python3.10 ([0205dd1](https://github.com/kap-sh/zapros/commit/0205dd1b4d81444e5671a56bed503025a1334d12))

## [0.2.2](https://github.com/kap-sh/zapros/compare/zapros-v0.2.1...zapros-v0.2.2) (2026-03-14)


### Documentation

* fix the github link ([896d993](https://github.com/kap-sh/zapros/commit/896d993eac8cae667bd82dc71b3a151681f06cc2))

## [0.2.1](https://github.com/kap-sh/zapros/compare/zapros-v0.2.0...zapros-v0.2.1) (2026-03-14)


### Features

* initial release ([35b7dc5](https://github.com/kap-sh/zapros/commit/35b7dc5b931c1dbea788e1076652847543c31acb))

## [0.2.0](https://github.com/kap-sh/zapros/compare/v0.1.1...v0.2.0) (2026-03-14)


### Features

* initial release ([35b7dc5](https://github.com/kap-sh/zapros/commit/35b7dc5b931c1dbea788e1076652847543c31acb))

## 0.1.0 (2026-03-13)


### Features

* add default handler ([c216d8b](https://github.com/kap-sh/zapros/commit/c216d8bc0d2333188b67d3a382a5121cc98b8e03))
* add pyreqwest backend ([0533d82](https://github.com/kap-sh/zapros/commit/0533d82aa085b95c0731cd5822ea222b67d45a53))
* add support for multipart ([459f209](https://github.com/kap-sh/zapros/commit/459f209b1c6d0bdf13e34d8d9b9e730e0af543d7))
