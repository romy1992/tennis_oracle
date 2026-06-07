type MessageProps = {
  title: string;
  message?: string;
};

export function LoadingState({ title = "Caricamento..." }: Partial<MessageProps>) {
  return <div className="state state-loading">{title}</div>;
}

export function ErrorState({ title, message }: MessageProps) {
  return (
    <div className="state state-error">
      <strong>{title}</strong>
      {message ? <span>{message}</span> : null}
    </div>
  );
}

export function EmptyState({ title, message }: MessageProps) {
  return (
    <div className="state">
      <strong>{title}</strong>
      {message ? <span>{message}</span> : null}
    </div>
  );
}
