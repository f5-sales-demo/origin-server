export default {
  branches: ['main'],
  plugins: [
    [
      '@semantic-release/commit-analyzer',
      {
        preset: 'angular',
        releaseRules: [
          { breaking: true, release: 'major' },
          { type: 'feat', release: 'minor' },
          { type: 'fix', release: 'patch' },
          { type: 'perf', release: 'patch' },
          { type: 'revert', release: 'patch' },
          { type: 'refactor', release: 'patch' },
          { type: 'chore', release: 'patch' },
        ],
      },
    ],
    '@semantic-release/release-notes-generator',
    // biome-ignore lint/suspicious/noTemplateCurlyInString: semantic-release interpolation token
    ['@semantic-release/exec', { prepareCmd: 'node scripts/stamp-manifest.js ${nextRelease.version}' }],
    ['@semantic-release/github', { assets: [{ path: 'manifest.json', label: 'Endpoint Manifest' }] }],
  ],
};
