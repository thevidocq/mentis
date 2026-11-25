import { PageHead } from "../layouts/AdminShell";

export function Placeholder({ title, text }: { title: string; text: string }) {
  return (
    <>
      <PageHead title={title} />
      <div className="page-body">
        <div className="notice muted">{text}</div>
      </div>
    </>
  );
}
