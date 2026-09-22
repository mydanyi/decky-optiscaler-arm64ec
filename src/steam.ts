
const DETAILS_TIMEOUT_MS = 3000;

// AppDetails only arrives through a subscription, so reading it is a one-shot
// registration with a timeout. The backend keeps a localconfig.vdf fallback.
export function readLaunchOptions(appid: number): Promise<string | null> {
  return new Promise((resolve) => {
    let settled = false;
    let registration: { unregister: () => void } | undefined;

    const finish = (value: string | null) => {
      if (settled) return;
      settled = true;
      // Unregister out of band: tearing down a subscription from inside its
      // own callback is not safe in the Steam client.
      setTimeout(() => {
        try {
          registration?.unregister();
        } catch {
          /* already gone */
        }
      }, 0);
      resolve(value);
    };

    try {
      registration = SteamClient.Apps.RegisterForAppDetails(appid, (details: any) => {
        finish(typeof details?.strLaunchOptions === "string" ? details.strLaunchOptions : "");
      });
    } catch {
      resolve(null);
      return;
    }

    setTimeout(() => finish(null), DETAILS_TIMEOUT_MS);
  });
}

export function writeLaunchOptions(appid: number, options: string): boolean {
  try {
    SteamClient.Apps.SetAppLaunchOptions(appid, options);
    return true;
  } catch {
    return false;
  }
}
