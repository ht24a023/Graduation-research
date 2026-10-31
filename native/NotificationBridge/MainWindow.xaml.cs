using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using Windows.Foundation;
using Windows.Storage.Streams;
using Windows.UI.Notifications;
using Windows.UI.Notifications.Management;

namespace NotificationBridge;
public partial class MainWindow : Window
{
    private readonly HttpClient client = new(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(4) };
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(1) };
    private readonly HashSet<string> seen = new();
    private UserNotificationListener? listener;
    private bool busy, baseline;
    private int generation = -1;
    private string endpoint = "";
    private string configuration = Path.Combine(AppContext.BaseDirectory, "bridge-config.json");

    public MainWindow()
    {
        InitializeComponent();
        Loaded += async (_, _) => { LoadConnection(); await Poll(); timer.Start(); };
        timer.Tick += async (_, _) => await Poll();
        Closed += (_, _) => { timer.Stop(); client.Dispose(); };
    }

    private bool LoadConnection()
    {
        try
        {
            using var config = JsonDocument.Parse(File.ReadAllText(configuration));
            string url = config.RootElement.GetProperty("endpoint").GetString() ?? "";
            string token = config.RootElement.GetProperty("token").GetString() ?? "";
            var uri = new Uri(url);
            if (uri.Scheme != "http" || uri.Host != "127.0.0.1" || token.Length < 32)
                throw new InvalidOperationException();
            endpoint = url.TrimEnd('/');
            client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
            listener ??= UserNotificationListener.Current;
            return true;
        }
        catch
        {
            StatusText.Text = "Web UIのSETTINGSから「Windows通知アクセスを設定」を押してください。未登録の場合はInstall.ps1でアプリ登録が必要です。";
            return false;
        }
    }

    private async void Allow_Click(object sender, RoutedEventArgs e)
    {
        if (!LoadConnection()) return;
        AllowButton.IsEnabled = false;
        try
        {
            // Dispatcher上のUIイベントからだけ、Windowsの許可要求を呼ぶ。
            var access = await listener!.RequestAccessAsync();
            StatusText.Text = access == UserNotificationListenerAccessStatus.Allowed
                ? "許可されました。Web UIの通知設定をオンにすると、新しく届いた通知を表示します。"
                : "アクセスは許可されていません。Windowsの設定 → プライバシーとセキュリティ → 通知 から確認できます。";
            baseline = false;
            await Poll();
        }
        catch (Exception ex)
        {
            StatusText.Text = "Windowsの通知アクセスを取得できません。アプリ登録・通知の許可を確認してください。（" + ex.GetType().Name + "）";
            try { await Send("error", []); } catch { /* 接続停止中でも許可画面を維持する。 */ }
        }
        finally { AllowButton.IsEnabled = true; }
    }

    private async Task Send(string state, List<object> notifications)
    {
        using var response = await client.PostAsJsonAsync(endpoint + "/notifications/bridge", new { state, notifications });
        response.EnsureSuccessStatusCode();
    }

    private static string Key(UserNotification notification) => notification.Id + ":" + notification.CreationTime.ToUnixTimeMilliseconds();

    private static async Task<string?> ReadIcon(UserNotification notification)
    {
        try
        {
            using var stream = await notification.AppInfo.DisplayInfo.GetLogo(new Windows.Foundation.Size(32, 32)).OpenReadAsync();
            if (stream.Size == 0 || stream.Size > 65536) return null;
            using var reader = new DataReader(stream);
            await reader.LoadAsync((uint)stream.Size);
            byte[] bytes = new byte[(int)stream.Size]; reader.ReadBytes(bytes);
            var mime = bytes.Length > 8 && bytes[0] == 137 && bytes[1] == 80 ? "image/png"
                : bytes.Length > 3 && bytes[0] == 255 && bytes[1] == 216 ? "image/jpeg" : null;
            return mime == null ? null : "data:" + mime + ";base64," + Convert.ToBase64String(bytes);
        }
        catch { return null; }
    }

    private async Task Poll()
    {
        if (busy || string.IsNullOrEmpty(endpoint)) return;
        busy = true;
        try
        {
            // Web UIのOFFを最初に確認し、OFFの間はOSの通知一覧を取得しない。
            using var response = await client.GetAsync(endpoint + "/notifications/bridge");
            if ((int)response.StatusCode == 401) { LoadConnection(); return; }
            response.EnsureSuccessStatusCode();
            using var data = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            int nextGeneration = data.RootElement.GetProperty("generation").GetInt32();
            bool enabled = data.RootElement.GetProperty("enabled").GetBoolean();
            if (generation != nextGeneration) { generation = nextGeneration; baseline = false; seen.Clear(); }
            var access = listener!.GetAccessStatus();
            string state = access == UserNotificationListenerAccessStatus.Allowed ? "allowed"
                : access == UserNotificationListenerAccessStatus.Denied ? "denied" : "unspecified";
            if (!enabled || state != "allowed")
            {
                baseline = false; seen.Clear(); await Send(state, []);
                StatusText.Text = !enabled ? "Web UIで通知表示がOFFです。通知本文は取得していません。" : "Windowsの許可が必要です。上のボタンから許可してください。";
                return;
            }
            var notifications = await listener.GetNotificationsAsync(NotificationKinds.Toast);
            if (!baseline)
            {
                foreach (var item in notifications) seen.Add(Key(item));
                baseline = true; await Send("allowed", []);
                StatusText.Text = "接続中。新しく届いたアプリ通知だけを、このPCのUIへ渡しています。";
                return;
            }
            var fresh = new List<object>();
            foreach (var notification in notifications.OrderBy(item => item.CreationTime))
            {
                string key = Key(notification);
                if (!seen.Add(key)) continue;
                try
                {
                    var binding = notification.Notification.Visual.GetBinding(KnownNotificationBindings.ToastGeneric);
                    if (binding == null) continue;
                    var elements = binding.GetTextElements();
                    fresh.Add(new { id = key, app = notification.AppInfo.DisplayInfo.DisplayName,
                        title = elements.FirstOrDefault()?.Text ?? "",
                        body = string.Join(" ", elements.Skip(1).Select(item => item.Text)),
                        created_at = notification.CreationTime.ToUnixTimeMilliseconds()/1000.0,
                        icon = await ReadIcon(notification) });
                }
                catch { /* 1件の形式不備で他アプリの通知を止めない。 */ }
            }
            if (seen.Count > 1024) { seen.Clear(); foreach (var item in notifications) seen.Add(Key(item)); }
            if (fresh.Count == 0) await Send("allowed", fresh);
            else foreach (var batch in fresh.Chunk(20)) await Send("allowed", batch.ToList());
        }
        catch { StatusText.Text = "Web UIとの接続を確認しています。サーバーを再起動した場合はSETTINGSから再接続してください。"; }
        finally { busy = false; }
    }
}
