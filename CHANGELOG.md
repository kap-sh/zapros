# Changelog

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
