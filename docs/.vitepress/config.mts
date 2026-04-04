import { defineConfig } from "vitepress";

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: "Zapros",
  description: "Modern and extensible HTTP client for Python",
  head: [
    [
      "link",
      {
        rel: "icon",
        type: "image/jpeg",
        sizes: "32x32",
        href: "/red-spider.png",
      },
    ],
    [
      "link",
      {
        rel: "icon",
        type: "image/jpeg",
        sizes: "64x64",
        href: "/red-spider.png",
      },
    ],
    [
      "link",
      {
        rel: "apple-touch-icon",
        sizes: "180x180",
        href: "/red-spider.png",
      },
    ],
  ],
  themeConfig: {
    logo: { src: "/red-spider.png", width: 42, height: 48 },
    siteTitle: "Zapros",
    search: {
      provider: "local",
    },
    nav: [
      // { text: 'Home', link: '/' },
      // { text: 'Examples', link: '/markdown-examples' }
    ],

    sidebar: [
      {
        text: "Introduction",
        items: [
          { text: "Overview", link: "/overview" },
          { text: "Quickstart", link: "/quickstart" },
          { text: "Configuration", link: "/configuration" },
        ],
      },
      {
        text: "Making Requests",
        items: [
          { text: "GET Requests", link: "/get-requests" },
          { text: "Query Parameters", link: "/query-parameters" },
          { text: "Request Body", link: "/request-body" },
          { text: "URLs", link: "/urls" },
          { text: "Core Models", link: "/models" },
        ],
      },
      {
        text: "Handlers",
        items: [
          { text: "Standard Library", link: "/python-std" },
          { text: "Browser", link: "/browser" },
          { text: "asgi", link: "/asgi" },
          { text: "Rust", link: "/rust" },
        ],
      },
      {
        text: "Common Features",
        items: [
          { text: "Authentication", link: "/authentication" },
          { text: "Cookies", link: "/cookies" },
          { text: "Redirects", link: "/redirects" },
          { text: "Retries", link: "/retries" },
          { text: "Caching", link: "/caching" },
          { text: "Custom Handlers", link: "/handlers" },
        ],
      },
      {
        text: "Testing",
        items: [
          { text: "Mocking HTTP Requests", link: "/mocking" },
          { text: "HTTP Cassettes", link: "/cassettes" },
        ],
      },
    ],

    socialLinks: [{ icon: "github", link: "https://github.com/kap-sh/zapros" }],
  },
});
