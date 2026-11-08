import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.predrive.ai',
  appName: 'PreDrive AI',
  webDir: 'dist',
  server: {
    androidScheme: 'https',
  },
};

export default config;

