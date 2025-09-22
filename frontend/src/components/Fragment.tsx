"use client";

import React, { useEffect } from 'react';
import { useFragment } from '@/contexts/FragmentContext';
import { Button } from '@/components/ui/button';
import { X, Copy, Download, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';

export function Fragment() {
  const { isVisible, title, content, language, path, closeFragment } = useFragment();

  if (!isVisible) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
    } catch (err) {
      console.error('Failed to copy content:', err);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = path || title || 'fragment.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  useEffect(() => {
    console.log('Fragment state:', { isVisible, title, content: content?.substring(0, 100) + '...', language, path });
  }, [isVisible, title, content, language, path]);

  return (
    <div className={cn(
      "fixed top-0 right-0 h-full w-1/2 bg-background border-l border-border z-50 flex flex-col shadow-lg",
      "transition-transform duration-300 ease-in-out",
      isVisible ? "translate-x-0" : "translate-x-full"
    )}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border bg-muted/30">
        <div className="flex items-center gap-3">
          <FileText className="h-5 w-5 text-primary" />
          <div className="flex flex-col">
            <h3 className="font-semibold text-sm">{title || 'Artifact'}</h3>
            {path && (
              <p className="text-xs text-muted-foreground">{path}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            className="h-8 w-8 p-0 hover:bg-muted"
            title="Copy content"
          >
            <Copy className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDownload}
            className="h-8 w-8 p-0 hover:bg-muted"
            title="Download file"
          >
            <Download className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={closeFragment}
            className="h-8 w-8 p-0 hover:bg-muted"
            title="Close artifact"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        <div className="p-4">
          <div className={cn(
            "rounded-lg border bg-card text-card-foreground shadow-sm",
            "overflow-hidden"
          )}>
            <div className="bg-muted/50 px-4 py-2 border-b">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                {language || 'text'}
              </span>
            </div>
            <pre className={cn(
              "text-sm font-mono whitespace-pre-wrap break-words",
              "p-4 overflow-auto max-h-[calc(100vh-200px)]",
              "bg-background"
            )}>
              <code className={language ? `language-${language}` : ''}>
                {content || 'No content available'}
              </code>
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}