import { Sparkles } from "lucide-react";

import { TopBar } from "../components/TopBar";

export function ComingSoon({ title, description }: { title: string; description: string }) {
  return (
    <>
      <TopBar title={title} />
      <div className="grid place-items-center px-8 py-24 animate-fade-in">
        <div className="max-w-sm text-center">
          <span className="mx-auto grid size-12 place-items-center rounded-xl bg-brand-50 text-brand-600">
            <Sparkles className="size-6" aria-hidden />
          </span>
          <h2 className="mt-4 text-base font-semibold">{title} is on its way</h2>
          <p className="mt-1 text-sm text-slate-500">{description}</p>
        </div>
      </div>
    </>
  );
}
