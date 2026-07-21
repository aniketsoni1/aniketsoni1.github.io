# Gemfile - local Jekyll development.
#
# On GitHub Pages the site is built with the `github-pages` gem, so this
# file exists mainly so you can run `bundle exec jekyll serve` locally and
# match the Pages build. jekyll-feed / jekyll-seo-tag / jekyll-sitemap are
# all bundled by `github-pages`, so they render on Pages with no extra work.

source "https://rubygems.org"

# Pin to the GitHub Pages build to reproduce production locally.
gem "github-pages", group: :jekyll_plugins

# Plugins (also transitively provided by github-pages; listed for clarity).
group :jekyll_plugins do
  gem "jekyll-feed"
  gem "jekyll-seo-tag"
  gem "jekyll-sitemap"
end

# Windows / JRuby friendliness (harmless elsewhere).
platforms :mingw, :x64_mingw, :mswin, :jruby do
  gem "tzinfo", ">= 1", "< 3"
  gem "tzinfo-data"
end
gem "wdm", "~> 0.1.1", :platforms => [:mingw, :x64_mingw, :mswin]

# Fixes a Ruby 3.x change where webrick is no longer bundled.
gem "webrick", "~> 1.8"
