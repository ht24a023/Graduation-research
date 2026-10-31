# Windows通知補助アプリ

通常のPython実行にはWindowsアプリのパッケージIDがないため、通知アクセスを担当する小さなWPFアプリを分離しています。Pythonから通知データベースを直接読む方法や、Windowsの許可を回避する方法は使用しません。

## 準備済みのもの

- `publish/NotificationBridge.exe`：ビルド済みの補助アプリ。
- `Package.appxmanifest`：`userNotificationListener` と `runFullTrust` を宣言したアプリ登録用マニフェスト。
- `Build.ps1`：.NET 9 SDKを使う再ビルド。
- `Install.ps1`：現在のWindowsユーザーへの開発用アプリ登録。Windowsの設定は変更しません。
- `Uninstall.ps1`：この補助アプリの登録と接続情報のみを削除。

.NET 9 Desktop RuntimeとWindows 10 version 2004以降が必要です。このPCではビルドとWindows SDKによるパッケージの検証を実施済みです。Windowsへの登録と、実際の通知アクセス許可は未実施です。

## 初回セットアップ

1. 未署名の開発用アプリを登録するため、Windowsの設定で「開発者モード」が有効か確認します。有効化するかは利用者が判断してください。スクリプトが勝手に有効化することはありません。
2. PowerShellでこのリポジトリのルートへ移動し、`./native/NotificationBridge/Install.ps1` を実行します。スクリプトが組織のポリシーで禁止されている場合は、そのポリシーに従ってください。
3. Pythonサーバーを起動または再起動します。
4. 同じPCのブラウザーでWeb UIを開き、`SETTINGS` → `Windows通知アクセスを設定` を押します。
5. 補助アプリの画面で `Windowsの通知アクセスを許可する` を押し、Windows側の許可を行います。
6. Web UIの `Windows通知をUIに表示する` をオンにします。最初に存在する通知は表示せず、その後に新しく届いたアプリ通知を表示します。

補助アプリのウィンドウを閉じると取得は止まります。サーバーを再起動した場合はSETTINGSから再接続してください。通知表示の初期状態はOFFで、サーバー再起動後もOFFになります。

## 取得範囲と扱い

取得対象はWindows通知センターのアプリ通知のうち、ToastGenericとして取得できるものです。Windowsの許可、管理ポリシー、通知元の形式により取得できない場合があります。UAC画面やアプリ独自のポップアップすべてを取得する機能ではありません。

アプリ名、タイトル、本文、生成時刻、取得可能なPNG/JPEGアイコンを渡します。Windows APIから共通の重要度を取得できるとは限らないため、オレンジ色表示はWeb UIで「重要扱い」と指定したアプリ名に基づきます。

- OFFの間はWindows通知一覧を取得しません。
- 有効化直後は通知のIDを初期化し、過去の通知をまとめて表示しません。
- 接続先は認証トークン付きの `http://127.0.0.1` だけです。外部サーバーやAIへ通知本文を送りません。
- Pythonは本文を最大60秒だけメモリー保持し、ファイル・チャット・研究用ログに保存しません。
- UIをCHATへ切り替える・タブを隠す・設定をOFFにすると表示と待ち行列を消去します。
- ×ボタンはWeb UIのポップアップだけを閉じます。Windows通知の削除・既読化は行いません。
- 接続トークンが入る `publish/bridge-config.json` はGit管理と配布パッケージの対象外です。

## 根拠となる公式仕様

- [Microsoft Notification listener](https://learn.microsoft.com/en-us/windows/apps/develop/notifications/app-notifications/notification-listener)：アプリのcapability、UIスレッドでの許可要求、アクセス状態の再確認、ToastGenericとアプリアイコン。
- [外部配置のパッケージID](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/grant-identity-to-nonpackaged-apps)：Win32アプリへのパッケージID。
- [uap3:Capability](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-uap3-capability-manual)：userNotificationListenerの宣言。
