# Origin Server

🌐 English |
[日本語](https://f5-sales-demo.github.io/origin-server/ja/) |
[한국어](https://f5-sales-demo.github.io/origin-server/ko/) |
[简体中文](https://f5-sales-demo.github.io/origin-server/zh-cn/) |
[繁體中文](https://f5-sales-demo.github.io/origin-server/zh-tw/) |
[Español](https://f5-sales-demo.github.io/origin-server/es/) |
[Português](https://f5-sales-demo.github.io/origin-server/pt-br/) |
[Français](https://f5-sales-demo.github.io/origin-server/fr/) |
[Deutsch](https://f5-sales-demo.github.io/origin-server/de/) |
[Italiano](https://f5-sales-demo.github.io/origin-server/it/) |
[العربية](https://f5-sales-demo.github.io/origin-server/ar/) |
[हिन्दी](https://f5-sales-demo.github.io/origin-server/hi/) |
[ไทย](https://f5-sales-demo.github.io/origin-server/th/)

[![GitHub Pages Deploy](https://github.com/f5-sales-demo/origin-server/actions/workflows/github-pages-deploy.yml/badge.svg)](https://github.com/f5-sales-demo/origin-server/actions/workflows/github-pages-deploy.yml)
[![Repository Settings](https://github.com/f5-sales-demo/origin-server/actions/workflows/enforce-repo-settings.yml/badge.svg)](https://github.com/f5-sales-demo/origin-server/actions/workflows/enforce-repo-settings.yml)
[![Release](https://github.com/f5-sales-demo/origin-server/actions/workflows/release.yml/badge.svg)](https://github.com/f5-sales-demo/origin-server/actions/workflows/release.yml)
[![License](https://img.shields.io/github/license/f5-sales-demo/origin-server)](LICENSE)

Supported origin deployments for authorized F5 Distributed Cloud demos: the Azure full-origin nine-application stack and a separate AWS Juice Shop-only module.

## Documentation

Full documentation is available at __[https://f5-sales-demo.github.io/origin-server/](https://f5-sales-demo.github.io/origin-server/)__.

## Supported deployments

| Offering | Scope | Runtime | Terraform |
| --- | --- | --- | --- |
| _Azure full-origin_ | Nine applications across 41 containers, fronted by nginx | Ubuntu 24.04 Azure VM | [`terraform/`](terraform/) |
| _AWS Juice Shop_ | OWASP Juice Shop only; not the nine-application stack | Private AWS Fargate tasks behind an ALB | [`terraform/modules/aws-juice-shop/`](https://github.com/f5-sales-demo/origin-server/tree/d6384bb0621c4c1eceb38d55a6b63e7b9cc7083a/terraform/modules/aws-juice-shop) |

See the [architecture guide](https://f5-sales-demo.github.io/origin-server/01-architecture/) to choose the correct deployment.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow rules,
branch naming, and CI requirements.

## License

See [LICENSE](LICENSE).
